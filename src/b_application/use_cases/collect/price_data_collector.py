from datetime import datetime, timedelta

from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.ports.market.market_data_provider import IMarketDataProvider
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.b_application.schemas.config import AppConfig
from src.b_application.schemas.stock_candidate import StockCandidate


class PriceDataCollector:
    """
    Use Case: Orchestrates the collection of market data.
    Combines Real-time bars (Hot) with Historical bars (Cold) to form a complete context.
    """

    def __init__(
        self,
        market_data_provider: IMarketDataProvider,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._market_data_provider = market_data_provider
        self._config = config
        self._logger = logger

    async def execute(self, candidates: list[StockCandidate]) -> list[AnalysisContext]:
        if not candidates:
            return []

        self._logger.info(f"Collecting price data for {len(candidates)} candidates...")

        # 1. Prepare Date Range for History (Application Logic)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self._config.analysis_lookback_days)

        # 2. Batch Fetch Real-time Bars (Intraday Data)
        stock_ids = [c.stock.stock_id for c in candidates]
        try:
            realtime_bars = await self._market_data_provider.fetch_realtime_bars(stock_ids)
        except Exception as e:
            self._logger.error(f"Failed to fetch realtime bars: {e}")
            return []

        contexts: list[AnalysisContext] = []

        for candidate in candidates:
            stock_id = candidate.stock.stock_id
            current_bar = realtime_bars.get(stock_id)

            # If we can't get the current price, we can't make a decision NOW.
            if not current_bar:
                self._logger.debug(f"Missing realtime data for {stock_id}. Skipping.")
                continue

            try:
                # 3. Fetch History (Historical Data)
                history = await self._market_data_provider.fetch_history(
                    stock_id=stock_id, start_date=start_date, end_date=end_date
                )

                # 4. Merge Data (Stitching)
                if history and history[-1].ts.date() == current_bar.ts.date():
                    # Replace the last bar (which might be incomplete in history) with the latest realtime bar
                    full_ohlcv = history[:-1] + [current_bar]
                else:
                    full_ohlcv = history + [current_bar]

                # 5. Initialize Context
                ctx = AnalysisContext(
                    stock=candidate.stock,
                    source=candidate.source,
                    trigger_reason=candidate.trigger_reason,
                    current_price=current_bar.close_price,
                    ohlcv_data=full_ohlcv,
                )
                contexts.append(ctx)

            except Exception as e:
                self._logger.error(f"Error processing {stock_id}: {e}")

        self._logger.success(f"Initialized {len(contexts)} analysis contexts.")
        return contexts
