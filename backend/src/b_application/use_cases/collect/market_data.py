"""
Use Case: Collect price data for stocks.
Fetches real-time bars and historical data, then merges them.
"""
from datetime import datetime, timedelta

from a_domain.model.market.stock import Stock
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.rules.collect.freshness import DataFreshnessRule
from b_application.schemas.config import AppConfig


class MarketData:
    """Enriches Stock with price data (realtime + historical)."""

    def __init__(
        self,
        market_provider: IPriceProvider,
        freshness_rule: DataFreshnessRule,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._market = market_provider
        self._freshness = freshness_rule
        self._config = config
        self._logger = logger

    async def execute(self, stocks: list[Stock]) -> list[Stock]:
        if not stocks:
            return []

        self._logger.info(f"Collecting prices for {len(stocks)} stocks...")

        end_date = datetime.now()
        start_date = end_date - timedelta(days=self._config.analysis_lookback_days)

        stock_ids = [s.stock_id for s in stocks]
        try:
            realtime_bars = await self._market.fetch_realtime_bars(stock_ids)
        except Exception as e:
            self._logger.error(f"Failed to fetch realtime bars: {e}")
            return []

        enriched: list[Stock] = []
        for stock in stocks:
            current_bar = realtime_bars.get(stock.stock_id)
            if not current_bar:
                self._logger.debug(f"Missing realtime data for {stock.stock_id}, skipping")
                continue

            # Data freshness check (WIRED)
            if not self._freshness.is_fresh(current_bar.ts):
                self._logger.debug(f"Stale data for {stock.stock_id}, skipping")
                continue

            try:
                history = await self._market.fetch_history(
                    stock_id=stock.stock_id, start_date=start_date, end_date=end_date,
                )
                if history and history[-1].ts.date() == current_bar.ts.date():
                    full_ohlcv = history[:-1] + [current_bar]
                else:
                    full_ohlcv = history + [current_bar]

                stock.ohlcv = full_ohlcv
                enriched.append(stock)
            except Exception as e:
                self._logger.error(f"Error collecting prices for {stock.stock_id}: {e}")

        self._logger.info(f"Collected prices for {len(enriched)} stocks")
        return enriched
