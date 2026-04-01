from datetime import datetime, timedelta

from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.collect.freshness import DataFreshnessRule
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


class MarketData:
    """
    Use Case: Collect price data for stocks.
    Fetches real-time bars and historical data concurrently.
    Enriches Stock with price data (realtime + historical).
    """

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

    async def execute(self, context: PipelineContext) -> None:
        stocks = context.candidates
        if not stocks:
            return

        self._logger.info(f"Collecting prices for {len(stocks)} stocks...")

        end_date = datetime.now()
        start_date = end_date - timedelta(days=self._config.analysis.lookback_days)

        try:
            realtime_bars = await self._market.fetch_realtime_bars(stocks)
            history_map = await self._market.fetch_history(stocks, start_date, end_date)
        except Exception as e:
            self._logger.error(f"Failed to fetch market data bulk: {e}")
            return

        enriched: list[Stock] = []

        # 2. Pure Business Logic Loop
        for stock in stocks:
            current_bar = realtime_bars.get(stock.stock_id)
            if not current_bar:
                self._logger.debug(f"Missing realtime data for {stock.stock_id}, skipping")
                continue

            if not self._freshness.is_fresh(current_bar.ts):
                self._logger.debug(f"Stale data for {stock.stock_id}, skipping")
                continue

            try:
                # Get the history we bulk-fetched
                history = history_map.get(stock.stock_id, [])

                # Replace today's historical candle with the realtime candle if they overlap
                if history and history[-1].ts.date() == current_bar.ts.date():
                    history.pop()

                history.append(current_bar)
                stock.ohlcv = history
                enriched.append(stock)

            except Exception as e:
                self._logger.error(f"Error processing prices for {stock.stock_id}: {e}")

        context.priced = enriched
        self._logger.info(f"Collected prices for {len(enriched)} stocks")
