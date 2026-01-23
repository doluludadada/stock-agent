from datetime import datetime, timedelta
from decimal import Decimal

from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.model.market.ohlcv import Ohlcv
from src.a_domain.model.market.stock import Stock
from src.a_domain.ports.market.market_data_port import IMarketDataPort
from src.a_domain.ports.system.logging_port import ILoggingPort
from src.b_application.configuration.schemas import AppConfig


class PriceDataCollector:
    """
    Use Case: Fetch OHLCV price history for stocks.

    Responsibility:
    - Fetch historical price data for each stock
    - Extract current price from latest candle
    - Populate AnalysisContext with price data
    """

    def __init__(
        self,
        market_data: IMarketDataPort,
        config: AppConfig,
        logger: ILoggingPort,
    ):
        self._market_data = market_data
        self._config = config
        self._logger = logger

    async def execute(self, stocks: list[Stock]) -> list[AnalysisContext]:
        """
        Collect price data for all provided stocks.

        Args:
            stocks: List of Stock entities to fetch price data for.

        Returns:
            List of AnalysisContext with ohlcv_data and current_price populated.
            Stocks with failed data fetch are excluded.
        """
        self._logger.info(f"Collecting price data for {len(stocks)} stocks")

        end_date = datetime.now()
        start_date = end_date - timedelta(days=self._config.analysis_lookback_days)

        contexts: list[AnalysisContext] = []

        for stock in stocks:
            try:
                ohlcv_data = await self._market_data.get_price_history(
                    stock_id=stock.stock_id,
                    start_date=start_date,
                    end_date=end_date,
                )

                if not ohlcv_data:
                    self._logger.warning(f"No price data for {stock.stock_id}, skipping")
                    continue

                current_price = self._extract_current_price(ohlcv_data)

                context = AnalysisContext(
                    stock=stock,
                    ohlcv_data=ohlcv_data,
                    current_price=current_price,
                )
                contexts.append(context)

            except Exception as e:
                self._logger.error(f"Failed to fetch price data for {stock.stock_id}: {e}")
                continue

        self._logger.success(f"Price data collected for {len(contexts)}/{len(stocks)} stocks")
        return contexts

    def _extract_current_price(self, ohlcv_data: list[Ohlcv]) -> Decimal:
        """Extract current price from the most recent candle."""
        sorted_data = sorted(ohlcv_data, key=lambda x: x.ts, reverse=True)
        return sorted_data[0].close_price
