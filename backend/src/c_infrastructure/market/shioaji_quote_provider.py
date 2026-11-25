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
    is the client of the latest login that succeeded, else of the first, and `login` the latest login in its thread.
    `up_clients` holds every client whose login succeeded and that Shioaji has not reported down since: Solace calls the
    session-down callback from its own thread once its reconnects gave up, and a request whose token Shioaji refused
    marks its client down (sdk_request), since the SDK then disconnects the session itself and calls no callback. It is
    keyed by id(): no client is ever collected, so an id names one client for the life of the process, and a dict's set
    and pop are each one step, as log_in's thread and Solace's write it at once. `logged_in_at` is when the login of
    `client` succeeded, by the market clock, None before one did. `failed_at` is when the latest login failed and
    `failures` how many failed in a row (retrying). `pace` paces every market-data request on the login, whichever
    runtime makes it, since Shioaji counts its 50 market-data queries per 10 seconds per login. `earlier_clients` keeps
    every other client a login was made on for the life of the process, failed ones too, none logged out or collected.
    """

    client: Shioaji
    up_clients: dict[int, Shioaji] = field(default_factory=dict)
    login: asyncio.Future[None] | None = None
    logged_in_at: datetime | None = None
    failed_at: datetime | None = None
    failures: int = 0
    pace: RequestPace = field(default_factory=RequestPace)
    earlier_clients: list[Shioaji] = field(default_factory=list)

    @property
    def up(self) -> bool:
        """The latest login, the one the site's realtime quotes are read on, is up."""
        return self.up_on(self.client)

    def up_on(self, client: Shioaji) -> bool:
        """
        Whether the login made on `client` is up: it succeeded and Shioaji has not reported it down since. A later login
        changes nothing of it, so a runtime's SinoPac orders on its own client until that client's login goes down.
        """
        return id(client) in self.up_clients

    def lost(self, client: Shioaji) -> None:
        """The login of `client` is down, whichever login it was."""
        self.up_clients.pop(id(client), None)

    def failed(self, at: datetime) -> None:
        """
        One more login in a row failed, at `at`: one that raised or returned no stock account in place of a SinoPac
        login that works (log_in), or one that came up without the SinoPac a renewal needed of it
        (RuntimeSwitch.log_in_again).
        """
        self.failed_at, self.failures = at, self.failures + 1

    def retrying(self, market_clock: IMarketClock, shioaji: ShioajiConfig) -> bool:
        """
        Whether it is within the wait after the latest failure, when no login is made: shioaji.login_retry_seconds after
        the first in a row, and after each further one twice the wait before, at most shioaji.login_retry_max_seconds. So
        a SinoPac that refuses all day is asked about a hundred times, each on one new client, not once a minute.
        """
        if self.failed_at is None:
            return False

        # An int and a float compare exactly, so a long run of failures never overflows a float.
        doublings = min(2 ** (self.failures - 1), shioaji.login_retry_max_seconds / shioaji.login_retry_seconds)
        return market_clock.now() < self.failed_at + timedelta(seconds=shioaji.login_retry_seconds * doublings)

    def stale(self, market_clock: IMarketClock, shioaji: ShioajiConfig) -> bool:
        """
        Whether the login of `client` was made before the latest market day's shioaji.login_renewal_time, so Shioaji's
        token, whose lifetime SinoPac does not state, and the day's contracts are renewed every market day before the
        session. A login whose time is not known is not stale.
        """
        return self.logged_in_at is not None and self.logged_in_at < market_clock.last_market_time(shioaji.login_renewal_time)

    def serves(self, replaced: Shioaji | None) -> bool:
        """
        Whether a runtime may open on the latest login now: while it is up, any, stale or not, when `replaced` is None;
        else only one on another client than `replaced`, the client whose login a renewal replaces.
        """
        return self.up and (replaced is None or self.client is not replaced)


@dataclass(frozen=True, slots=True)
class ShioajiSession:
    """
    One client of a connection, as a request is made on it (sdk_request): a runtime's broker keeps the client of the
    login it was opened on, and the quote provider asks the connection's latest. A refused token marks that client's
    login down (ShioajiConnection.lost).
    """

    connection: ShioajiConnection
    client: Shioaji


class ShioajiQuoteProvider(IBrokerQuoteProvider):
    """
    Sinopac's market data over the Shioaji client, on the simulation or the production server as the login says: each
    stock's snapshot for realtime quotes. The simulation server serves the same exchange data as production. Shioaji
    stamps market data with the Taipei wall-clock time as nanoseconds since the epoch read as if Taipei were UTC. The
    daily history comes from the exchanges' own reports instead (IDailyHistorySource).

    Every runtime's provider of one login reads the process's ShioajiConnection of that login, which the first logs in.
    After that only a renewal logs in again, once the latest login failed or went down or is on the client the renewal
    replaces (`replaced`). When Shioaji is the broker, ShioajiExecutionProvider orders on the client of the runtime's
    login. Where the site offers SinoPac (`checks_account`), a login that returns no stock account counts as failed
    while it would replace a SinoPac login that works, so a renewal never makes a site without SinoPac out of one that
    has it.

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
        checks_account: bool,
        replaced: Shioaji | None,
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
        self._checks_account = checks_account
        self._replaced = replaced

    @override
    async def connect(self) -> None:
        """
        Returns at once while a login the runtime may open on is up (ShioajiConnection.serves): any while there is no
        `replaced`; else one on another client. Otherwise it waits for the login under way, or logs in on a new client
        (the connection's first client for its first login) without subscribing to the account's order events (the
        broker polls its orders itself; its own orders' events go to log_order_event). The new client becomes the
        connection's once the login succeeded; the one before is kept, never logged out, and serves until then. Within
        the wait after a failed login (ShioajiConnection.retrying) it raises at once and makes none. The wait is
        shielded: a runtime that times out or is cancelled leaves the login running, and a later one takes it up
        instead of making another.

        Without `replaced` (a start, a reload, a save) it starts or waits for the connection's first login only: once a
        login of the connection ended, such an open while the latest login is down raises at once and makes none, so no
        reload waits for SinoPac within the switch's lock and api.settings_build_timeout_seconds. The next login is then
        the timer's look's or the CLI's round's (RuntimeSwitch.log_in_again).
        """
        connection = self._connection

        if connection.serves(self._replaced):
            return

        if self._replaced is None and (connection.logged_in_at is not None or connection.failures):
            raise RuntimeError("the login is down until the timer's look or the CLI's round logs in again")

        if connection.login is None or connection.login.done():
            if connection.retrying(self._clock, self._shioaji):
                raise RuntimeError("the wait after the last failed login has not passed (shioaji.login_retry_seconds, doubling)")

            client, events = (
                connection.client if connection.login is None else self._new_client(),
                partial(log_order_event, self._logger),
            )
            login = partial(log_in, connection, client, self._login, self._clock, events, self._checks_account)
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
            if snapshot.code in index_of and (quote := quote_of(snapshot, self._epoch, board_lot_shares=0)) is not None
        }


class LoginWithoutAccount(RuntimeError):
    """
    A login that returned no stock account on a site that offers SinoPac while the login before it works with one, which
    log_in counts as failed.
    """


def log_in(
    connection: ShioajiConnection,
    client: Shioaji,
    login: ShioajiLogin,
    market_clock: IMarketClock,
    order_events: Callable[[OrderState, Mapping[str, object]], None],
    checks_account: bool,
) -> None:
    """
    One login of `connection` on `client`, in a worker thread: once it succeeded, `client` is the connection's and up,
    with its session-down callback and its order events registered, and the client before it is kept. It is up before
    the callback is registered, so a session that goes down in between is not lost. A login that fails, or that
    returns no stock account where `checks_account` asks for SinoPac's and the connection's latest login is up with
    one, leaves the connection's client as it was, up or not, keeps `client` down and counts one more failure
    (ShioajiConnection.failed). A login without the stock account that replaces no working SinoPac login, the first one
    included, serves the quotes, and connect_sinopac offers no SinoPac on it.
    """
    try:
        client.login(api_key=login.api_key.get_secret_value(), secret_key=login.secret_key.get_secret_value(), subscribe_trade=False)

        if checks_account and client.stock_account is None and connection.up and connection.client.stock_account is not None:
            raise LoginWithoutAccount("the login returned no stock account, and the login before it has one")

        connection.up_clients[id(client)] = client
        client.set_session_down_callback(partial(connection.lost, client))
        client.set_order_callback(order_events)
    except Exception:
        connection.lost(client)
        connection.failed(market_clock.now())

        if client is not connection.client:
            connection.earlier_clients.append(client)

        raise

    if client is not connection.client:
        connection.earlier_clients.append(connection.client)

    connection.client, connection.logged_in_at, connection.failed_at, connection.failures = client, market_clock.now(), None, 0


def index_contracts_of(client: Shioaji, named: Mapping[MarketIndex, IndexQuoteContract]) -> dict[MarketIndex, Index]:
    """Shioaji's contract of each index it lists where the settings say it keeps it. The lookup waits for the login's contracts."""
    listed = client.Contracts.Indexs
    exchanges = {index: listed[at.exchange] for index, at in named.items()}
    found = {index: exchanges[index][at.symbol] for index, at in named.items() if exchanges[index] is not None}
    return {index: contract for index, contract in found.items() if isinstance(contract, Index)}


def quote_of(snapshot: Snapshot, epoch: datetime, board_lot_shares: int) -> Ohlcv | None:
    """
    The session so far of a stock or an index, closing at the last trade and stamped with the exchange's time of that
    trade, with its change from the session's reference price. A snapshot with no volume of the session gets no quote:
    its price is the reference price, which nobody paid. Volumes count board lots of `board_lot_shares`; an index
    passes 0, since its bar has no volume of its own.

    After a session a snapshot is stamped 13:30 for a last trade in the closing auction and 14:30 for one in the
    after-hours fixed-price session. A stock that has not traded yet is stamped 08:30 of the day with a total volume of
    0. An index's snapshot counts its market's volume: TSE001 at 13:33 on 2026-11-17, 14,456,731 on the simulation login.
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
    (TokenError, the server's 401) marks the login of the session's client down (ShioajiConnection.lost): the SDK has
    disconnected the session then, so every later request on the client fails, and the timer's next look logs in again
    where that client's was the latest login.
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
