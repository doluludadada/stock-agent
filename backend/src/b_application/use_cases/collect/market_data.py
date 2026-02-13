"""
Use Case: Collect price data for candidates.

Fetches real-time bars and historical data, then merges them.
"""
from datetime import datetime, timedelta

from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.ports.market.market_provider import IMarketProvider
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.b_application.schemas.config import AppConfig


class MarketData:
    """
    Enriches Stock with price data (realtime + historical).
    """

    def __init__(
        self,
        market_provider: IMarketProvider,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._market = market_provider
        self._config = config
        self._logger = logger

    async def execute(self, candidates: list[Stock]) -> list[Stock]:
        if not candidates:
            return []

        self._logger.info(f"Collecting prices for {len(candidates)} candidates...")

        end_date = datetime.now()
        start_date = end_date - timedelta(days=self._config.analysis_lookback_days)

        stock_ids = [c.stock_id for c in candidates]
        try:
            realtime_bars = await self._market.fetch_realtime_bars(stock_ids)
        except Exception as e:
            self._logger.error(f"Failed to fetch realtime bars: {e}")
            return []

        enriched: list[Stock] = []

        for candidate in candidates:
            current_bar = realtime_bars.get(candidate.stock_id)

            if not current_bar:
                self._logger.debug(f"Missing realtime data for {candidate.stock_id}, skipping")
                continue

            try:
                history = await self._market.fetch_history(
                    stock_id=candidate.stock_id,
                    start_date=start_date,
                    end_date=end_date,
                )

                if history and history[-1].ts.date() == current_bar.ts.date():
                    full_ohlcv = history[:-1] + [current_bar]
                else:
                    full_ohlcv = history + [current_bar]

                candidate.ohlcv_data = full_ohlcv
                enriched.append(candidate)

            except Exception as e:
                self._logger.error(f"Error collecting prices for {candidate.stock_id}: {e}")

        self._logger.info(f"Collected prices for {len(enriched)} candidates")
        return enriched
