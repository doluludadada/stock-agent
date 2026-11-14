import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import override

from a_domain.model.market.article import Article
from a_domain.ports.market.news_provider import INewsProvider
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.market.stock_feed import IStockFeed
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock


class HeldStockFeed(IStockFeed):
    """
    The news sites' articles and the board's posts of each stock, held in memory for `freshness` after they were
    fetched, for the `held_stocks` stocks asked most recently. One fetch runs per stock at a time, so visitors who open
    the same page together wait for one request, and every answer within the window reaches no site. A source that
    raises or answers nothing keeps what was held of it, and the stock is not asked again until the window has passed,
    so a site that is down is asked once per window, not once per page view. Two stocks' fetches start at least `pause`
    apart, whoever asks, so the Web API's timer, which asks for one stock after another, and a burst of page views
    reach the sites one stock at a time and no faster. It lives with its runtime: a restart or a settings change starts
    empty. `board` is None where the site reads no board.
    """

    def __init__(
        self,
        news: INewsProvider,
        board: ISocialMediaProvider | None,
        market_clock: IMarketClock,
        freshness: timedelta,
        held_stocks: int,
        pause: timedelta,
        logger: ILoggingProvider,
    ) -> None:
        self._sources: dict[str, Callable[[str, int], Awaitable[list[Article]]]] = {"news": news.fetch_news}

        if board is not None:
            self._sources["board"] = board.fetch_stock_posts

        self._market_clock = market_clock
        self._freshness = freshness
        self._held_stocks = held_stocks
        self._pause = pause
        self._one_stock_at_a_time = asyncio.Lock()
        self._paced_until = market_clock.now()
        self._logger = logger
        self._held: OrderedDict[str, tuple[datetime, dict[str, list[Article]]]] = OrderedDict()
        self._fetching: dict[str, asyncio.Lock] = {}

    @override
    async def fetch(self, stock_id: str, limit: int) -> list[Article]:
        async with self._fetching.setdefault(stock_id, asyncio.Lock()):
            fetched_at, held = self._held.get(stock_id, (None, {}))

            if fetched_at is None or self._market_clock.now() - fetched_at > self._freshness:
                found: dict[str, list[Article]] = {}

                async with self._one_stock_at_a_time:
                    await asyncio.sleep(max(0.0, (self._paced_until - self._market_clock.now()).total_seconds()))

                    for name, source in self._sources.items():
                        try:
                            found[name] = await source(stock_id, limit) or held.get(name, [])
                        except Exception as error:
                            self._logger.warning(
                                f"Stock page {name} of {stock_id} failed, serving what is held: {type(error).__name__}"
                            )
                            found[name] = held.get(name, [])

                    self._paced_until = self._market_clock.now() + self._pause

                held = found
                self._held[stock_id] = (self._market_clock.now(), held)

            self._held.move_to_end(stock_id)

            while len(self._held) > self._held_stocks:
                self._fetching.pop(self._held.popitem(last=False)[0], None)

            return [article for articles in held.values() for article in articles]
