"""
Use Case: Collect price data for candidates.

Fetches real-time bars and historical data, then merges them.
"""
from datetime import datetime, timedelta

from backend.src.a_domain.model.analysis.stock_candidate import StockCandidate
from backend.src.a_domain.ports.market.market_data_provider import IMarketDataProvider
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.b_application.schemas.config import AppConfig


class CollectPrices:
    """
    Enriches StockCandidate with price data (realtime + historical).

    Flow:
    1. Batch fetch realtime bars for all candidates
    2. For each candidate, fetch historical data
    3. Merge realtime + history into complete OHLCV series
    """

    def __init__(
        self,
        market_data_provider: IMarketDataProvider,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._market = market_data_provider
        self._config = config
        self._logger = logger

    async def execute(self, candidates: list[StockCandidate]) -> list[StockCandidate]:
        if not candidates:
            return []

        self._logger.info(f"Collecting prices for {len(candidates)} candidates...")

        end_date = datetime.now()
        start_date = end_date - timedelta(days=self._config.analysis_lookback_days)

        stock_ids = [candidate.stock.stock_id for candidate in candidates]
        try:
            realtime_bars = await self._market.fetch_realtime_bars(stock_ids)
        except Exception as e:
            self._logger.error(f"Failed to fetch realtime bars: {e}")
            return []

        enriched: list[StockCandidate] = []

        for candidate in candidates:
            stock_id = candidate.stock.stock_id
            current_bar = realtime_bars.get(stock_id)

            if not current_bar:
                self._logger.debug(f"Missing realtime data for {stock_id}, skipping")
                continue

            try:
                history = await self._market.fetch_history(
                    stock_id=stock_id,
                    start_date=start_date,
                    end_date=end_date,
                )

                # Merge: replace last bar if same date, otherwise append
                if history and history[-1].ts.date() == current_bar.ts.date():
                    full_ohlcv = history[:-1] + [current_bar]
                else:
                    full_ohlcv = history + [current_bar]

                candidate.ohlcv_data = full_ohlcv
                enriched.append(candidate)

            except Exception as e:
                self._logger.error(f"Error collecting prices for {stock_id}: {e}")

        self._logger.info(f"Collected prices for {len(enriched)} candidates")
        return enriched
