import asyncio
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from typing import override

import c_infrastructure.trading.shioaji.sdk_reporting  # noqa: F401

# isort: split
from shioaji import Shioaji
from shioaji.constant import OrderState
from shioaji.contracts import Index
from shioaji.data import Snapshot
from shioaji.error import TokenError

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.broker_quote_provider import IBrokerQuoteProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import MarketIndex
from a_domain.types.errors import BrokerNotAnswering
from b_application.config.market_data_config import IndexQuoteContract, MarketDataConfig
from b_application.config.trading_config import ShioajiConfig, ShioajiLogin
from c_infrastructure.request_pace import RequestPace
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE


@dataclass(eq=False)
class ShioajiConnection:
    """
    The process's link to Shioaji on one login, which the quote provider of every runtime on that login shares. `client`
    is the client of the latest login that succeeded, else of the first, and `login` the latest login in its thread. `up`
    says the login of `client` succeeded and Shioaji has not reported it down since: Solace calls the session-down
    callback from its own thread once its reconnects gave up, and a request whose token Shioaji refused marks it down
    (sdk_request), since the SDK then disconnects the session itself and calls no callback. `logged_in_at` is when that
    login succeeded, by the market clock, None before one did; `failed_at` when the latest login failed. `pace` paces
    every market-data request on the login, whichever runtime makes it, since Shioaji counts its 50 market-data queries
    per 10 seconds per login. `earlier_clients` keeps every other client a login was made on for the life of the
    process, none logged out or collected.
    """

    client: Shioaji
    up: bool = False
    login: asyncio.Future[None] | None = None
    logged_in_at: datetime | None = None
    failed_at: datetime | None = None
    pace: RequestPace = field(default_factory=RequestPace)
    earlier_clients: list[Shioaji] = field(default_factory=list)

    def lost(self, client: Shioaji) -> None:
        """The login of `client` is down, while `client` is still the connection's: a later login's client stays up."""
        if self.client is client:
            self.up = False

    def due(self, market_clock: IMarketClock, shioaji: ShioajiConfig, opened_on: datetime | None) -> bool:
        """
        Whether a login is to be made again now: the login of `client` failed, went down, or is stale, made before the
        latest market day's shioaji.login_renewal_time, so that Shioaji's token, whose lifetime SinoPac does not state,
        is renewed every market day before the session; and no login failed within shioaji.login_retry_seconds, so a
        SinoPac that does not answer is not asked again at once. A connection whose login time is not known is not stale.
        Also due, to be taken up rather than made, while the login of `client` is up and is not the one the asker
        opened on (`opened_on`, when that one succeeded): a runtime that stopped waiting for a login left it running,
        and it succeeded since. connect asks on the latest login, `logged_in_at`.
        """
        now = market_clock.now()

        if self.failed_at is not None and now < self.failed_at + timedelta(seconds=shioaji.login_retry_seconds):
            return False

        if self.up and self.logged_in_at != opened_on:
            return True

        renewal = market_clock.last_market_time(shioaji.login_renewal_time)
        return not self.up or (self.logged_in_at is not None and self.logged_in_at < renewal)


@dataclass(frozen=True, slots=True)
class ShioajiSession:
    """
    One client of a connection, as a request is made on it (sdk_request): a runtime's broker keeps the client of the
    login it was opened on, and the quote provider asks the connection's latest. A refused token marks that client's
    login down, and only while it is still the connection's (ShioajiConnection.lost).
    """

    connection: ShioajiConnection
    client: Shioaji


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
        shioaji: ShioajiConfig,
        market_clock: IMarketClock,
        market_data: MarketDataConfig,
        board_lot_shares: int,
        logger: ILoggingProvider,
    ) -> None:
        self._connection = connection
        self._new_client = new_client
        self._login = login
        self._shioaji = shioaji
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
        Logs in without subscribing to the account's order events (the broker polls its orders itself; its own orders'
        events go to log_order_event), unless the login is up and not stale (ShioajiConnection.due), and waits for it. A
        login that failed, went down or is stale is made again on a new client, which becomes the connection's once the
        login succeeded; the one before is kept, never logged out, and a stale one serves until then. Within
        shioaji.login_retry_seconds of a failed login it raises at once and makes none. The wait is shielded: a reload
        that times out or is cancelled leaves the login running, and the next runtime waits for the same login instead
        of making another.
        """
        connection = self._connection

        if connection.login is None or connection.login.done():
            if not connection.due(self._clock, self._shioaji, connection.logged_in_at):
                if connection.up:
                    return

                raise RuntimeError(f"a login failed within shioaji.login_retry_seconds ({self._shioaji.login_retry_seconds:g})")

            client, events = (
                connection.client if connection.login is None else self._new_client(),
                partial(log_order_event, self._logger),
            )
            login = partial(log_in, connection, client, self._login, self._clock, events)
            connection.login = asyncio.get_running_loop().run_in_executor(None, login)

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
            batch, session = contracts[offset : offset + self._batch_size], ShioajiSession(self._connection, self._connection.client)
            await self._connection.pace.wait(self._quote_interval_seconds)
            snapshots: list[Snapshot] = await sdk_request(session, session.client.snapshots, batch, timeout=self._timeout_milliseconds)
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
        session = ShioajiSession(self._connection, self._connection.client)
        snapshots: list[Snapshot] = await sdk_request(
            session, session.client.snapshots, list(contracts.values()), timeout=self._timeout_milliseconds
        )
        index_of = {contract.code: index for index, contract in contracts.items()}
        return {
            index_of[snapshot.code]: quote
            for snapshot in snapshots
            if snapshot.code in index_of and (quote := index_quote_of(snapshot, self._epoch)) is not None
        }


def log_in(
    connection: ShioajiConnection,
    client: Shioaji,
    login: ShioajiLogin,
    market_clock: IMarketClock,
    order_events: Callable[[OrderState, Mapping[str, object]], None],
) -> None:
    """
    One login of `connection` on `client`, in a worker thread: once it succeeded, `client` is the connection's and up,
    with its session-down callback and its order events registered, and the client before it is kept. A login that
    fails leaves the connection's client as it was, up or not, keeps `client` and says when it failed.
    """
    api_key, secret_key = login.api_key.get_secret_value(), login.secret_key.get_secret_value()

    try:
        client.login(api_key=api_key, secret_key=secret_key, subscribe_trade=False)
        client.set_session_down_callback(partial(connection.lost, client))
        client.set_order_callback(order_events)
    except Exception:
        connection.failed_at = market_clock.now()

        if client is not connection.client:
            connection.earlier_clients.append(client)

        raise

    if client is not connection.client:
        connection.earlier_clients.append(connection.client)

    connection.client, connection.up, connection.logged_in_at, connection.failed_at = client, True, market_clock.now(), None


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
    session: ShioajiSession, call: Callable[Arguments, Answer], *args: Arguments.args, **kwargs: Arguments.kwargs
) -> Answer:
    """
    Makes one request of the SDK on `session`'s client, `call` with its arguments in a worker thread. Its failure raises
    BrokerNotAnswering saying what failure_of says of the SDK's error, never the error's text. A refused token
    (TokenError, the server's 401) marks the session's login down (ShioajiConnection.lost): the SDK has disconnected the
    session then, so every later request on the client fails, and the next runtime logs in again.
    """
    try:
        return await asyncio.to_thread(call, *args, **kwargs)
    except Exception as error:
        if isinstance(error, TokenError):
            session.connection.lost(session.client)

        raise BrokerNotAnswering(f"Shioaji answered {failure_of(error)}") from None


def log_order_event(logger: ILoggingProvider, state: OrderState, event: Mapping[str, object]) -> None:
    """
    Shioaji's order callback, which the SDK calls from a thread of its own: one INFO line per event, the deal trail
    of the production log, of the order's tag (custom_field, the first hex digits of the journal's order id and the
    part's index, so a line names its journal row), the stock, the action, the lot, the quantity and the price, and for
    an order event its operation's type and code; a deal event's quantity and price are the deal's. The event also
    holds the account, the login's person id, the operation's message and the order's other ids, so nothing else of it
    is read. It never raises into the SDK: an event it cannot read is one WARNING line that names the error's type only.
    """
    try:
        if state in (OrderState.StockDeal, OrderState.FuturesDeal):
            stock = f"{event.get('action')} {event.get('code')} {event.get('order_lot')}"
            logger.info(f"Shioaji deal tagged {event.get('custom_field')}: {stock} {event.get('quantity')} at {event.get('price')}")
            return

        order, operation, contract = (event_section(event, key) for key in ("order", "operation", "contract"))
        stock = f"{order.get('action')} {contract.get('code')} {order.get('order_lot')}"
        logger.info(
            f"Shioaji order event {operation.get('op_type')} {operation.get('op_code')} tagged {order.get('custom_field')}: "
            f"{stock} {order.get('quantity')} at {order.get('price')}"
        )

    except Exception as error:
        logger.warning(f"Shioaji order event not logged: {type(error).__name__}")


def event_section(event: Mapping[str, object], key: str) -> Mapping[str, object]:
    """The section `key` of an order event, or nothing where the event has no such section."""
    section = event.get(key)
    return section if isinstance(section, Mapping) else {}


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
