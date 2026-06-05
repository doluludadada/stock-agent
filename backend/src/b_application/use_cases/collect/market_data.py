from icontract import require

from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
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
        price_provider: IPriceProvider,
        logger: ILoggingProvider,
        config: AppConfig,
        market_clock: IMarketClock,
    ):
        self._price = price_provider
        self._freshness = DataFreshnessRule()
        self._logger = logger
        self._config = config
        self._clock = market_clock

    @require(lambda context: len(context.candidates) > 0, "Pipeline guarantees candidates exist")
    async def execute(self, context: PipelineContext) -> None:
        stocks = context.candidates

        self._logger.info(f"Collecting prices for {len(stocks)} stocks.")

        start_date, end_date = self._clock.history_window(self._config.analysis.lookback_days)

        try:
            realtime_bars = await self._price.fetch_realtime_bars(stocks)
            history_map = await self._price.fetch_history(stocks, start_date, end_date)

        except Exception as exc:
            self._logger.error(f"Failed to fetch market data bulk: {exc}")
            return

        enriched: list[Stock] = []

        for stock in stocks:
            current_bar = realtime_bars.get(stock.stock_id)

            if current_bar is None:
                self._logger.debug(f"Missing realtime data for {stock.stock_id}, skipping")
                continue

            if not self._freshness.is_fresh(current_bar.ts):
                self._logger.debug(f"Stale data for {stock.stock_id}, skipping")
                continue

            history = history_map.get(stock.stock_id, [])
            current_day = self._clock.to_trading_date(current_bar.ts)

            history = [bar for bar in history if self._clock.to_trading_date(bar.ts) != current_day]

            history.append(current_bar)

            stock.ohlcv = sorted(
                history,
                key=lambda bar: self._clock.to_trading_date(bar.ts),
            )
            enriched.append(stock)

        context.priced = enriched
        self._logger.info(f"Collected prices for {len(enriched)} stocks")
