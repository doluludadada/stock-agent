from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.technical.calculation import TechnicalIndicatorCalculator
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


class MarketDataCollector:
    """Loads OHLCV history and calculates indicators for current analysis candidates."""

    def __init__(
        self,
        ohlcv_provider: IOhlcvProvider,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._ohlcv_provider = ohlcv_provider
        self._market_clock = market_clock
        self._lookback_days = config.analysis.lookback_days
        self._indicator_calculator = TechnicalIndicatorCalculator(config.indicators)
        self._logger = logger

    async def execute(self, stocks: list[Stock], context: PipelineContext) -> None:
        start_date, end_date = self._market_clock.history_window(self._lookback_days)
        self._logger.info(f"Fetching OHLCV data for {len(stocks)} analysis candidates...")

        try:
            history_by_stock_id = await self._ohlcv_provider.fetch_history(
                stocks=stocks,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as error:
            error_message = f"Failed to fetch market data: {error}"
            self._logger.error(error_message)
            context.stats.add_error(error_message)
            return

        collected_count = 0

        for stock in stocks:
            stock.ohlcv = []
            stock.indicators = None

            bars = list(history_by_stock_id.get(stock.stock_id, []))

            if not bars:
                self._logger.warning(f"Market data unavailable: {stock.stock_id}")
                continue

            stock.ohlcv = bars
            stock.indicators = self._indicator_calculator.calculate(bars)
            collected_count += 1

        self._logger.success(f"Collected market data for {collected_count}/{len(stocks)} analysis candidates.")
