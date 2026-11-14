from datetime import date

from a_domain.ports.market.cached_price_provider import ICachedPriceProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import MarketType
from b_application.config.app_config import AppConfig


class DailyHistoryBackfill:
    """
    Brings the exchanges' history cache up to the last settled session: each exchange's index and ex-right references
    and every session's reported bars, each saved as it comes (ICachedPriceProvider.sync). Given `first`, it goes back
    to that day. Without one, as the Web API's timer runs it, it covers the window of
    market_data.history_backfill_bars, the stock page's longest chart: on its first run that is a backfill, and after
    it the sessions that closed since. Either way it asks again every session held without any change, as Shioaji's
    daily quotes saved them, which a read does not wait for. A request that fails, a timeout included, stops it there
    and keeps what it saved, so a rerun asks only for what is still missing. It answers the sessions the cache holds
    reported bars of, the index sessions it still lacks them of, and each exchange's ranges it could not read, of its
    index and of its ex-right references alike: a history with a range of either unread is not whole. `cache` is None
    where the daily history is the open-data archive's (public), which its own step fills, and the answer is None.
    """

    def __init__(self, cache: ICachedPriceProvider | None, market_clock: IMarketClock, config: AppConfig) -> None:
        self._cache = cache
        self._market_clock = market_clock
        self._history_days = config.analysis.history_days(config.market_data.history_backfill_bars)

    async def execute(self, first: date | None = None) -> tuple[list[date], list[date], list[tuple[MarketType, date, date]]] | None:
        if self._cache is None:
            return None

        window = (
            self._market_clock.history_window(self._history_days)
            if first is None
            else (self._market_clock.session_close(first), self._market_clock.now())
        )
        start, last = await self._cache.sync(*window, reported=True)
        index = await self._cache.index_sessions(start, last)
        held = await self._cache.held_sessions(start, last, reported=True)
        sessions = {self._market_clock.to_trading_date(bar.ts) for bars in index.values() for bar in bars}
        unread = [
            (market, *gap)
            for market in MarketType
            for gap in [
                *await self._cache.index_gaps(market, start, last),
                *sorted(await self._cache.reference_gaps(market, start, last)),
            ]
        ]

        return sorted(held), sorted(sessions - held), list(dict.fromkeys(unread))
