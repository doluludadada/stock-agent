# backend/src/b_application/use_cases/collect/market_scanner.py

from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


class MarketScanner:
    """Fetches the entire market universe for after-hours full scanning and enriches OHLCV."""

    def __init__(
        self,
        stock_provider: IStockProvider,
        price_provider: IPriceProvider,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._stock_provider = stock_provider
        self._price_provider = price_provider
        self._market_clock = market_clock
        self._config = config
        self._logger = logger

    async def execute(self, context: PipelineContext) -> None:
        self._logger.info("Scanning full stock universe...")
        stocks = await self._stock_provider.get_all()

        context.candidates = stocks
        context.stats.total_scanned = len(stocks)
        self._logger.info(f"Loaded {len(stocks)} stocks into pipeline.")

        # Determine the time window for historical data
        start_date, end_date = self._market_clock.history_window(self._config.analysis.lookback_days)

        self._logger.info("Fetching OHLCV data to enrich candidates...")

        try:
            # Fetch history for all stocks (YahooFinanceProvider handles batching internally)
            history_data = await self._price_provider.fetch_history(
                stocks=stocks,
                start_date=start_date,
                end_date=end_date,
            )

            # Loop through candidates and enrich them
            success_count = 0
            for stock in context.candidates:
                bars = history_data.get(stock.stock_id)
                if bars:
                    stock.ohlcv = bars
                    success_count += 1

            self._logger.success(f"Enriched {success_count}/{len(stocks)} stocks with OHLCV data.")

        except Exception as e:
            error_message = f"Failed to fetch market data: {e}"
            self._logger.error(error_message)
            context.stats.add_error(error_message)
