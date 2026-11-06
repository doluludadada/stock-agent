import asyncio
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import groupby
from math import isfinite
from typing import override

import c_infrastructure.trading.shioaji.sdk_reporting  # noqa: F401

# isort: split
from shioaji import Shioaji
from shioaji.data import Snapshot

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.broker_quote_provider import IBrokerQuoteProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import MarketType
from b_application.config.market_data_config import MarketDataConfig
from b_application.config.sources_config import ShioajiSources
from b_application.config.trading_config import ShioajiLogin
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE


@dataclass(eq=False)
class ShioajiConnection:
    """
    The process's link to Shioaji on one login, which the quote provider of every runtime on that login shares. `client`
    is the client of the latest login and `login` that login in its thread. `up` says the login succeeded and Shioaji has
    not reported its session down since: Solace calls the session-down callback from its own thread once its reconnects
    gave up. `request_slot` and `last_request_at` pace every request on the login, whichever runtime makes it, since
    Shioaji counts its 50 market-data queries per 10 seconds per login. `earlier_clients` keeps every client a login was
    made on before `client` for the life of the process: none is logged out or collected, because shioaji 1.3.1 on
    Python 3.14 segfaults at the next garbage collection after a logout.
    """

    client: Shioaji
    up: bool = False
    login: asyncio.Future[None] | None = None
    request_slot: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_request_at: float | None = None
    earlier_clients: list[Shioaji] = field(default_factory=list)


class ShioajiQuoteProvider(IBrokerQuoteProvider[Snapshot]):
    """
    Sinopac's market data over the Shioaji client, on the simulation or the production server as the login says: each
    stock's snapshot for realtime quotes, one daily-quotes request per session for every listed stock's daily bar, and
    the one-minute bars of each exchange's own index (sources.shioaji.index_codes) for its daily history. The simulation
    server serves the same exchange data as production. Shioaji stamps market data with the Taipei wall-clock time as
    nanoseconds since the epoch read as if Taipei were UTC.

    Every runtime's provider of one login reads the process's ShioajiConnection of that login, which the first logs in
    and a later one logs in again only once the login failed or went down. When Shioaji is the broker,
    ShioajiExecutionProvider orders on the client of the runtime's login.

    Shioaji allows 50 market-data queries per 10 seconds, snapshots, ticks and kbars together, and stops answering
    for a minute after one more. So requests on one login go one at a time, from every runtime: a snapshots request, of
    at most market_data.quote_batch_size stocks, at least market_data.quote_request_interval_seconds after the request
    before it, and a daily-history request at least market_data.history_request_interval_seconds after it.
    """

    def __init__(
        self,
        connection: ShioajiConnection,
        new_client: Callable[[], Shioaji],
        login: ShioajiLogin,
        market_clock: IMarketClock,
        market_data: MarketDataConfig,
        sources: ShioajiSources,
        board_lot_shares: int,
        logger: ILoggingProvider,
    ) -> None:
        self._connection = connection
        self._new_client = new_client
        self._login = login
        self._clock = market_clock
        self._epoch = datetime(1970, 1, 1, tzinfo=TAIWAN_TIMEZONE)
        self._batch_size = market_data.quote_batch_size
        self._timeout_milliseconds = round(market_data.quote_timeout_seconds * 1000)
        self._quote_interval_seconds = market_data.quote_request_interval_seconds
        self._history_interval_seconds = market_data.history_request_interval_seconds
        self._index_window = timedelta(days=market_data.index_minutes_window_days - 1)
        self._index_codes = sources.index_codes
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
            raise RuntimeError(self.failure_of(error)) from None

    @override
    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        """A stock Shioaji has no contract for gets no quote."""
        requested = list(dict.fromkeys(stock.stock_id for stock in stocks))
        snapshots = await self.snapshots(requested)
        quotes = {snapshot.code: quote for snapshot in snapshots if (quote := self.quote_of(snapshot)) is not None}

        self._logger.info(f"Shioaji quotes: {len(quotes)}/{len(requested)} stocks with a trade this session")
        return quotes

    @override
    async def snapshots(self, stock_ids: Collection[str]) -> list[Snapshot]:
        """The contract lookup waits while the login still fetches the contracts."""
        stocks = self._connection.client.Contracts.Stocks
        contracts = await asyncio.to_thread(lambda: [found for code in stock_ids if (found := stocks[code]) is not None])
        answers: list[Snapshot] = []

        for offset in range(0, len(contracts), self._batch_size):
            batch, client = contracts[offset : offset + self._batch_size], self._connection.client
            answer = await self.request(self._quote_interval_seconds, client.snapshots, batch, timeout=self._timeout_milliseconds)
            answers.extend(answer)

        return answers

    @override
    def quote_of(self, snapshot: Snapshot) -> Ohlcv | None:
        """
        After a session a snapshot is stamped 13:30 for a last trade in the closing auction and 14:30 for one in the
        after-hours fixed-price session. A stock that has not traded yet is stamped 08:30 of the day with a total
        volume of 0. Volumes count board lots.
        """
        if snapshot.total_volume <= 0:
            return None

        return Ohlcv(
            ts=self._epoch + timedelta(microseconds=snapshot.ts // 1000),
            open=snapshot.open,
            high=snapshot.high,
            low=snapshot.low,
            close=snapshot.close,
            volume=snapshot.total_volume * self._board_lot_shares,
            change=snapshot.change_price,
        )

    @override
    async def fetch_session_bars(self, session: date) -> dict[str, Ohlcv]:
        """
        Shioaji's daily quotes, measured on the simulation server on 2026-11-06: one answer holds every listed stock of
        both exchanges with a four-digit code (1991), with the exchanges' official prices and shares traded, and a stock
        without a trade has no prices (NaN) and volume 0. A weekend, a holiday or a date to come answers no rows.
        """
        daily_quotes = self._connection.client.daily_quotes
        answer = await self.request(self._history_interval_seconds, daily_quotes, date=session, timeout=self._timeout_milliseconds)
        rows = zip(answer.Date, answer.Code, answer.Open, answer.High, answer.Low, answer.Close, answer.Volume, strict=True)
        stamp = self._clock.session_close(session)
        bars = {
            code: Ohlcv(ts=stamp, open=open_price, high=high, low=low, close=close, volume=volume)
            for day, code, open_price, high, low, close, volume in rows
            if day == session and volume > 0 and isfinite(close)
        }

        self._logger.info(f"Shioaji daily quotes of {session}: {len(bars)} stocks with a trade")
        return bars

    @override
    async def fetch_session_changes(self, session: date, stock_ids: Collection[str]) -> dict[str, float]:
        return {
            snapshot.code: quote.change
            for snapshot in await self.snapshots(stock_ids)
            if (quote := self.quote_of(snapshot)) is not None and quote.change is not None and quote.ts.date() == session
        }

    @override
    async def fetch_index_bars(self, market: MarketType, first: date, last: date) -> list[Ohlcv]:
        """The server refuses one-minute bars over more than market_data.index_minutes_window_days, so they come in windows."""
        contract = await asyncio.to_thread(lambda: self._connection.client.Contracts.Indexs[self._index_codes[market]])
        minutes: list[Ohlcv] = []
        start = first

        while start <= last:
            end = min(start + self._index_window, last)
            window = {"start": start.isoformat(), "end": end.isoformat(), "timeout": self._timeout_milliseconds}
            kbars = await self.request(self._history_interval_seconds, self._connection.client.kbars, contract, **window)
            columns = zip(kbars.ts, kbars.Open, kbars.High, kbars.Low, kbars.Close, kbars.Volume, strict=True)
            minutes += [
                Ohlcv(
                    ts=self._epoch + timedelta(microseconds=ts // 1000),
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
                for ts, open_price, high, low, close, volume in columns
            ]
            start = end + timedelta(days=1)

        bars = self.daily_bars(minutes)
        self._logger.info(f"Shioaji index bars of {market.value} from {first} to {last}: {len(bars)} sessions")
        return bars

    @override
    def daily_bars(self, minutes: Sequence[Ohlcv]) -> list[Ohlcv]:
        """An index's volume counts board lots, like a snapshot's."""
        bars: list[Ohlcv] = []

        for session, run in groupby(minutes, key=lambda minute: minute.ts.date()):
            day = list(run)
            bars.append(
                Ohlcv(
                    ts=self._clock.session_close(session),
                    open=day[0].open,
                    high=max(minute.high for minute in day),
                    low=min(minute.low for minute in day),
                    close=day[-1].close,
                    volume=sum(minute.volume for minute in day) * self._board_lot_shares,
                    change=day[-1].close - bars[-1].close if bars else None,
                )
            )

        return bars

    @override
    async def request[**Arguments, Answer](
        self, interval_seconds: float, call: Callable[Arguments, Answer], *args: Arguments.args, **kwargs: Arguments.kwargs
    ) -> Answer:
        connection = self._connection

        async with connection.request_slot:
            if connection.last_request_at is not None:
                await asyncio.sleep(max(0.0, interval_seconds - (time.monotonic() - connection.last_request_at)))

            connection.last_request_at = time.monotonic()

        try:
            return await asyncio.to_thread(call, *args, **kwargs)
        except Exception as error:
            raise RuntimeError(f"Shioaji answered {self.failure_of(error)}") from None

    @override
    def failure_of(self, error: Exception) -> str:
        """The SDK's errors carry the server's status as `code`, or as status.status_code of the answer they hold."""
        answer = error.args[0] if error.args and isinstance(error.args[0], dict) else {}
        status = getattr(error, "code", None)

        if status is None and isinstance(answer.get("status"), dict):
            status = answer["status"].get("status_code")

        return type(error).__name__ if status is None else f"{type(error).__name__}, status {status}"
