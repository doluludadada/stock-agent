from datetime import date

from a_domain.ports.market.cached_price_provider import ICachedPriceProvider
from a_domain.ports.system.market_clock import IMarketClock
from b_application.config.app_config import AppConfig


class DailyHistoryRefresh:
    """
    Brings the exchanges' history cache up to the last settled session over the window of
    market_data.history_backfill_bars, the stock page's longest chart: on its first run that is a backfill, and after
    it the sessions that closed since. It also asks again every session held without any change, as Shioaji's daily
    quotes saved them, which a read does not wait for. `cache` is None where the daily history comes from the open-data
    archive, which its own step fills, and then there is nothing to do.
    """

    def __init__(self, cache: ICachedPriceProvider | None, market_clock: IMarketClock, config: AppConfig) -> None:
        self._cache = cache
        self._market_clock = market_clock
        self._history_days = config.analysis.history_days(config.market_data.history_backfill_bars)

    async def execute(self) -> tuple[date, date] | None:
        if self._cache is None:
            return None

        return await self._cache.sync(*self._market_clock.history_window(self._history_days), reported=True)
