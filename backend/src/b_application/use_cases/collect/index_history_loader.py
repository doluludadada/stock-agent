from a_domain.model.market.ohlcv import Ohlcv
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import MarketIndex
from b_application.config.app_config import AppConfig


class IndexHistoryLoader:
    """
    A market index's daily bars, oldest first, over the calendar window that `required_bars` bars need, from the
    history cache the stock pages share. It fetches no realtime quote.
    """

    def __init__(self, ohlcv_provider: IOhlcvProvider, market_clock: IMarketClock, config: AppConfig) -> None:
        self._ohlcv_provider = ohlcv_provider
        self._market_clock = market_clock
        self._history_days = config.analysis.history_days

    async def execute(self, index: MarketIndex, required_bars: int) -> list[Ohlcv]:
        window = self._market_clock.history_window(self._history_days(required_bars))
        return await self._ohlcv_provider.fetch_index_history(index, *window)
