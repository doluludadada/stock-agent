from asyncio import Lock, sleep
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import override

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.broker_quote_provider import IBrokerQuoteProvider
from a_domain.ports.market.price_provider import IQuoteBoard, IRealtimeQuoteProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import MarketIndex
from b_application.config.market_data_config import MarketDataConfig


class QuoteBoard(IQuoteBoard):
    """
    The pages' realtime quotes of one runtime, in memory: the stocks of the quote source and the market indexes of the
    broker's market data, each kind followed on its own (FollowedQuotes). A kind's request never waits for the other
    kind's, and its answer or failure counts for that kind alone, so a slow or failing index request holds no stock
    page and keeps none asking after the close. The source paces every request with the orders' quotes on the same
    login.
    """

    def __init__(
        self,
        quote_provider: IRealtimeQuoteProvider,
        index_provider: IBrokerQuoteProvider | None,
        market_clock: IMarketClock,
        market_data: MarketDataConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._quote_provider = quote_provider
        self._index_provider = index_provider
        self._clock = market_clock
        self._stocks = FollowedQuotes[str]("stocks", market_data.quote_batch_size, market_data, market_clock, logger)
        self._indexes = FollowedQuotes[MarketIndex]("indexes", len(MarketIndex), market_data, market_clock, logger)

    @override
    async def follow(self, stock_ids: Collection[str], indexes: Collection[MarketIndex]) -> None:
        await self._stocks.follow(
            stock_ids, lambda wanted: self._quote_provider.fetch_realtime_bars([Stock(stock_id=stock_id) for stock_id in wanted])
        )
        await self._indexes.follow(indexes, lambda wanted: index_quotes_of(self._index_provider, wanted))

    @override
    def quotes(self, stock_ids: Collection[str], session: date) -> dict[str, Ohlcv]:
        return of_session(self._stocks.held, stock_ids, session, self._clock)

    @override
    def index_quotes(self, indexes: Collection[MarketIndex], session: date) -> dict[MarketIndex, Ohlcv]:
        return of_session(self._indexes.held, indexes, session, self._clock)

    @override
    def read_at(self, stock_ids: Collection[str], indexes: Collection[MarketIndex]) -> datetime | None:
        marks = [followed.read_at for followed, asked in ((self._stocks, stock_ids), (self._indexes, indexes)) if asked]
        return None if not marks or None in marks else min(mark for mark in marks if mark is not None)


@dataclass(eq=False)
class FollowedQuotes[Asked]:
    """
    One kind of quote the pages follow. A request of the source asks for what a page asked for within
    market_data.page_quote_idle_seconds, the latest asked first and at most `most` of them; of a page that asks for more
    at once, the first ones are followed. It leaves at least market_data.page_quote_refresh_seconds after the request
    before it. A page that asks for one never asked of the source does not wait that long: it waits until
    page_quote_first_seconds have passed since the last request and then makes the next, which also reads what every
    page asked for meanwhile. So the source gets at most one request of the kind per page_quote_first_seconds from every
    page together, and one per page_quote_refresh_seconds while the pages show the same. One request runs at a time and
    the pages that ask during it wait for its answer. A request that fails keeps the quotes held and counts for that
    pacing like any other, so it is made again no sooner; `read_at` is when the source last answered one.
    """

    kind: str
    most: int
    market_data: MarketDataConfig
    clock: IMarketClock
    logger: ILoggingProvider
    held: dict[Asked, Ohlcv | None] = field(default_factory=dict)
    read_at: datetime | None = None
    wanted_at: dict[Asked, datetime] = field(default_factory=dict)
    asked_at: datetime | None = None
    turn: Lock = field(default_factory=Lock)

    async def follow(self, asked: Collection[Asked], request: Callable[[list[Asked]], Awaitable[dict[Asked, Ohlcv]]]) -> None:
        """
        Notes that a page asks for these now, and asks the source once by `request` for what pages asked for lately
        when its pace allows.
        """
        followed = list(asked)[: self.most]

        if not followed:
            return

        self.wanted_at |= dict.fromkeys(followed, self.clock.now())

        async with self.turn:
            waited = None if self.asked_at is None else self.clock.now() - self.asked_at
            unread = any(key not in self.held for key in followed)

            if waited is not None and not unread and waited < timedelta(seconds=self.market_data.page_quote_refresh_seconds):
                return

            if waited is not None and waited < (first := timedelta(seconds=self.market_data.page_quote_first_seconds)):
                await sleep((first - waited).total_seconds())

            now = self.clock.now()
            self.wanted_at = asked_lately(self.wanted_at, now, timedelta(seconds=self.market_data.page_quote_idle_seconds), self.most)
            self.asked_at, wanted = now, list(self.wanted_at)
            quotes = await answered(request(wanted), f"{len(wanted)} {self.kind}", self.logger)
            self.read_at = now if quotes is not None else self.read_at
            self.held = {key: (quotes or {}).get(key) or self.held.get(key) for key in wanted}


def of_session[Asked](
    held: dict[Asked, Ohlcv | None], asked: Collection[Asked], session: date, clock: IMarketClock
) -> dict[Asked, Ohlcv]:
    """The quote held of each of these whose latest trade or value is of `session`."""
    return {key: quote for key in asked if (quote := held.get(key)) and clock.to_trading_date(quote.ts) == session}


def asked_lately[Asked](wanted_at: dict[Asked, datetime], now: datetime, idle: timedelta, most: int) -> dict[Asked, datetime]:
    """What a page asked for within `idle` of `now`, with when: the `most` asked for latest."""
    latest = sorted(wanted_at, key=wanted_at.__getitem__, reverse=True)[:most]
    return {asked: wanted_at[asked] for asked in latest if now - wanted_at[asked] <= idle}


async def answered[Asked](request: Awaitable[dict[Asked, Ohlcv]], asked: str, logger: ILoggingProvider) -> dict[Asked, Ohlcv] | None:
    """What one request answered, or None when it failed, which is logged."""
    try:
        return await request
    except Exception as error:
        logger.warning(f"Page quotes: {asked} not read: {type(error).__name__}")
        return None


async def index_quotes_of(provider: IBrokerQuoteProvider | None, indexes: list[MarketIndex]) -> dict[MarketIndex, Ohlcv]:
    """The broker's quote of each of these indexes, on a site with the broker's market data."""
    return await provider.fetch_index_quotes(indexes) if provider is not None else {}
