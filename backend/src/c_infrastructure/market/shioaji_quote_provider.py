import asyncio
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import override

import c_infrastructure.trading.shioaji.sdk_reporting  # noqa: F401

# isort: split
from shioaji import Shioaji
from shioaji.contracts import Index
from shioaji.data import Snapshot

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.broker_quote_provider import IBrokerQuoteProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import MarketIndex
from b_application.config.market_data_config import IndexQuoteContract, MarketDataConfig
from b_application.config.trading_config import ShioajiLogin
from c_infrastructure.request_pace import RequestPace
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE


@dataclass(eq=False)
class ShioajiConnection:
    """
    The process's link to Shioaji on one login, which the quote provider of every runtime on that login shares. `client`
    is the client of the latest login and `login` that login in its thread. `up` says the login succeeded and Shioaji has
    not reported its session down since: Solace calls the session-down callback from its own thread once its reconnects
    gave up. `pace` paces every market-data request on the login, whichever runtime makes it, since Shioaji counts its
    50 market-data queries per 10 seconds per login. `earlier_clients` keeps every client a login was
    made on before `client` for the life of the process: none is logged out or collected, because shioaji 1.3.1 on
    Python 3.14 segfaults at the next garbage collection after a logout.
    """

    client: Shioaji
    up: bool = False
    login: asyncio.Future[None] | None = None
    pace: RequestPace = field(default_factory=RequestPace)
    earlier_clients: list[Shioaji] = field(default_factory=list)


class ShioajiQuoteProvider(IBrokerQuoteProvider):
    """
    Sinopac's market data over the Shioaji client, on the simulation or the production server as the login says: each
    stock's snapshot for realtime quotes. The simulation server serves the same exchange data as production. Shioaji
    stamps market data with the Taipei wall-clock time as nanoseconds since the epoch read as if Taipei were UTC. The
    daily history comes from the exchanges' own reports instead (IDailyHistorySource).

    Every runtime's provider of one login reads the process's ShioajiConnection of that login, which the first logs in
    and a later one logs in again only once the login failed or went down. When Shioaji is the broker,
    ShioajiExecutionProvider orders on the client of the runtime's login.

    Shioaji allows 50 market-data queries per 10 seconds, snapshots, ticks and kbars together, and stops answering
    for a minute after one more. So requests on one login go one at a time, from every runtime: a snapshots request, of
    at most market_data.quote_batch_size stocks, at least market_data.quote_request_interval_seconds after the request
    before it. The market indexes are one more snapshots request in the same pace, of the contracts
    market_data.quote_index_contracts names; an index whose contract Shioaji does not list gets no quote, which is
    logged once.
    """

    def __init__(
        self,
        connection: ShioajiConnection,
        new_client: Callable[[], Shioaji],
        login: ShioajiLogin,
        market_clock: IMarketClock,
        market_data: MarketDataConfig,
        board_lot_shares: int,
        logger: ILoggingProvider,
    ) -> None:
        self._connection = connection
        self._new_client = new_client
        self._login = login
        self._clock = market_clock
        self._epoch = datetime(1970, 1, 1, tzinfo=TAIWAN_TIMEZONE)
        self._batch_size = market_data.quote_batch_size
        self._index_contracts = market_data.quote_index_contracts
        self._unlisted_indexes: set[MarketIndex] = set()
        self._timeout_milliseconds = round(market_data.quote_timeout_seconds * 1000)
        self._quote_interval_seconds = market_data.quote_request_interval_seconds
        self._board_lot_shares = board_lot_shares
        self._logger = logger

    @override
    async def connect(self) -> None:
        """
        Logs in without subscribing to the account's order events (the broker polls its orders itself), unless the
        login is up, and waits for it. A login that failed or went down is made again on a new client, and the one before
        is kept, never logged out. The wait is shielded: a reload that times out or is cancelled leaves the login
        running, and the next runtime waits for the same login instead of making another.
        """
        connection = self._connection

        if connection.up:
            return

        if connection.login is None or connection.login.done():
            if connection.login is not None:
                connection.earlier_clients.append(connection.client)
                connection.client = self._new_client()

            client, login = connection.client, self._login

            def gone_down() -> None:
                if connection.client is client:
                    connection.up = False

            def log_in() -> None:
                client.login(
                    api_key=login.api_key.get_secret_value(), secret_key=login.secret_key.get_secret_value(), subscribe_trade=False
                )
                client.set_session_down_callback(gone_down)
                connection.up = True

            connection.login = asyncio.get_running_loop().run_in_executor(None, log_in)

        try:
            await asyncio.shield(connection.login)
        except Exception as error:
            raise RuntimeError(failure_of(error)) from None

    @override
    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        """
        A stock Shioaji has no contract for gets no quote. The contract lookup waits while the login still fetches the
        contracts.
        """
        requested = list(dict.fromkeys(stock.stock_id for stock in stocks))
        listed = self._connection.client.Contracts.Stocks
        contracts = await asyncio.to_thread(lambda: [found for code in requested if (found := listed[code]) is not None])
        quotes: dict[str, Ohlcv] = {}

        for offset in range(0, len(contracts), self._batch_size):
            batch, client = contracts[offset : offset + self._batch_size], self._connection.client
            await self._connection.pace.wait(self._quote_interval_seconds)
            snapshots: list[Snapshot] = await sdk_request(client.snapshots, batch, timeout=self._timeout_milliseconds)
            quotes |= {
                snapshot.code: quote
                for snapshot in snapshots
                if (quote := quote_of(snapshot, self._epoch, self._board_lot_shares)) is not None
            }

        self._logger.info(f"Shioaji quotes: {len(quotes)}/{len(requested)} stocks with a trade this session")
        return quotes

    @override
    async def fetch_index_quotes(self, indexes: Collection[MarketIndex]) -> dict[MarketIndex, Ohlcv]:
        """
        An index is read from the contract the settings name. One without a contract there or in Shioaji's list gets no
        quote, which is logged the first time. A snapshot is matched to its index by the contract's code.
        """
        named = {index: self._index_contracts[index] for index in indexes if index in self._index_contracts}
        contracts = await asyncio.to_thread(index_contracts_of, self._connection.client, named)
        unlisted = set(indexes) - set(contracts) - self._unlisted_indexes
        self._unlisted_indexes |= unlisted

        if unlisted:
            self._logger.warning(f"Shioaji quotes: no index contract for {', '.join(sorted(unlisted))}, which gets no quote")

        if not contracts:
            return {}

        await self._connection.pace.wait(self._quote_interval_seconds)
        snapshots: list[Snapshot] = await sdk_request(
            self._connection.client.snapshots, list(contracts.values()), timeout=self._timeout_milliseconds
        )
        index_of = {contract.code: index for index, contract in contracts.items()}
        return {
            index_of[snapshot.code]: quote
            for snapshot in snapshots
            if snapshot.code in index_of and (quote := index_quote_of(snapshot, self._epoch)) is not None
        }


def index_contracts_of(client: Shioaji, named: Mapping[MarketIndex, IndexQuoteContract]) -> dict[MarketIndex, Index]:
    """Shioaji's contract of each index it lists where the settings say it keeps it. The lookup waits for the login's contracts."""
    listed = client.Contracts.Indexs
    exchanges = {index: listed[at.exchange] for index, at in named.items()}
    found = {index: exchanges[index][at.symbol] for index, at in named.items() if exchanges[index] is not None}
    return {index: contract for index, contract in found.items() if isinstance(contract, Index)}


def index_quote_of(snapshot: Snapshot, epoch: datetime) -> Ohlcv | None:
    """
    An index's session so far, closing at its latest value and stamped with the exchange's time of it, with its change
    from the previous close. As of a stock (quote_of), a snapshot with no volume of the session has no quote: before the
    session's first trade an index still stands at the previous close. The bar has no volume of its own.

    Measured on 2026-11-17 after the session on the simulation login: TSE001 at 13:33, 40092.11, a total volume of
    14,456,731.
    """
    if snapshot.total_volume <= 0:
        return None

    return Ohlcv(
        ts=epoch + timedelta(microseconds=snapshot.ts // 1000),
        open=snapshot.open,
        high=snapshot.high,
        low=snapshot.low,
        close=snapshot.close,
        change=snapshot.change_price,
    )


def quote_of(snapshot: Snapshot, epoch: datetime, board_lot_shares: int) -> Ohlcv | None:
    """
    The session so far, closing at the last trade and stamped with the exchange's time of that trade, with its change
    from the session's reference price. A stock that has not traded this session gets no quote: its price is the
    reference price, which nobody paid.

    After a session a snapshot is stamped 13:30 for a last trade in the closing auction and 14:30 for one in the
    after-hours fixed-price session. A stock that has not traded yet is stamped 08:30 of the day with a total
    volume of 0. Volumes count board lots.
    """
    if snapshot.total_volume <= 0:
        return None

    return Ohlcv(
        ts=epoch + timedelta(microseconds=snapshot.ts // 1000),
        open=snapshot.open,
        high=snapshot.high,
        low=snapshot.low,
        close=snapshot.close,
        volume=snapshot.total_volume * board_lot_shares,
        change=snapshot.change_price,
    )


async def sdk_request[**Arguments, Answer](
    call: Callable[Arguments, Answer], *args: Arguments.args, **kwargs: Arguments.kwargs
) -> Answer:
    """
    Makes one request of the SDK, `call` with its arguments in a worker thread. Its failure raises RuntimeError saying
    what failure_of says of the SDK's error, never the error's text.
    """
    try:
        return await asyncio.to_thread(call, *args, **kwargs)
    except Exception as error:
        raise RuntimeError(f"Shioaji answered {failure_of(error)}") from None


def failure_of(error: Exception) -> str:
    """
    What logs and run records may say of an error of the broker's SDK: its type and the server's status. Never its
    text, which holds the server's whole answer, the login's person id and addresses included.

    The SDK's errors carry the server's status as `code`, or as status.status_code of the answer they hold.
    """
    answer = error.args[0] if error.args and isinstance(error.args[0], dict) else {}
    status = getattr(error, "code", None)

    if status is None and isinstance(answer.get("status"), dict):
        status = answer["status"].get("status_code")

    return type(error).__name__ if status is None else f"{type(error).__name__}, status {status}"
