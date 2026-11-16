from asyncio import Lock, sleep
from collections.abc import Collection
from datetime import date, datetime, timedelta
from typing import override

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IQuoteBoard, IRealtimeQuoteProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from b_application.config.market_data_config import MarketDataConfig


class QuoteBoard(IQuoteBoard):
    """
    The pages' realtime quotes of one runtime, in memory. A request of the source asks for the stocks a page asked for
    within market_data.page_quote_idle_seconds, the latest asked first and at most market_data.quote_batch_size of
    them, which is one snapshots request of Shioaji; of a page that asks for more at once, the first ones are followed.
    It leaves at least market_data.page_quote_refresh_seconds after the request before it. A page that asks for a stock
    never asked of the source does not wait that long: it waits until page_quote_first_seconds have passed since the
    last request and then makes the next, which also reads the stocks of every page that asked meanwhile. So Shioaji
    gets at most one request per page_quote_first_seconds from every page together, and one per
    page_quote_refresh_seconds while the pages show the same stocks. One request runs at a time and the pages that ask
    during it wait for its answer. A request that fails counts for that pacing like any other, so it is made again no
    sooner. The source paces the request with the orders' quotes on the same login.
    """

    def __init__(
        self,
        quote_provider: IRealtimeQuoteProvider,
        market_clock: IMarketClock,
        market_data: MarketDataConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._quote_provider = quote_provider
        self._clock = market_clock
        self._refresh = timedelta(seconds=market_data.page_quote_refresh_seconds)
        self._first = timedelta(seconds=market_data.page_quote_first_seconds)
        self._idle = timedelta(seconds=market_data.page_quote_idle_seconds)
        self._round_size = market_data.quote_batch_size
        self._logger = logger
        self._wanted_at: dict[str, datetime] = {}
        self._held: dict[str, Ohlcv | None] = {}
        self._asked_at: datetime | None = None
        self._read_at: datetime | None = None
        self._turn = Lock()

    @override
    async def follow(self, stock_ids: Collection[str]) -> None:
        asked = list(stock_ids)[: self._round_size]
        self._wanted_at |= dict.fromkeys(asked, self._clock.now())

        async with self._turn:
            waited = None if self._asked_at is None else self._clock.now() - self._asked_at
            unread = any(stock_id not in self._held for stock_id in asked)

            if waited is not None and not unread and waited < self._refresh:
                return

            if waited is not None and waited < self._first:
                await sleep((self._first - waited).total_seconds())

            now = self._clock.now()
            latest = sorted(self._wanted_at, key=self._wanted_at.__getitem__, reverse=True)[: self._round_size]
            followed = [stock_id for stock_id in latest if now - self._wanted_at[stock_id] <= self._idle]
            self._wanted_at = {stock_id: self._wanted_at[stock_id] for stock_id in followed}
            self._asked_at = now
            quotes: dict[str, Ohlcv] = {}

            try:
                quotes = await self._quote_provider.fetch_realtime_bars([Stock(stock_id=stock_id) for stock_id in followed])
                self._read_at = now
            except Exception as error:
                self._logger.warning(f"Page quotes: {len(followed)} stocks not read: {type(error).__name__}")

            self._held = {stock_id: quotes.get(stock_id) or self._held.get(stock_id) for stock_id in followed}

    @override
    def quotes(self, stock_ids: Collection[str], session: date) -> dict[str, Ohlcv]:
        held = {stock_id: self._held.get(stock_id) for stock_id in stock_ids}
        return {stock_id: quote for stock_id, quote in held.items() if quote and self._clock.to_trading_date(quote.ts) == session}

    @override
    def read_at(self) -> datetime | None:
        return self._read_at
