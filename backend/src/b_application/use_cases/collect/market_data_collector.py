from datetime import datetime

from a_domain.model.indicators.technical_indicators import TechnicalIndicators
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.collect.freshness import DataFreshnessRule
from a_domain.rules.technical.calculation import (
    IndicatorParameters,
    TechnicalIndicatorCalculator,
)
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class MarketDataCollector:
    """
    Loads historical and realtime market data.

    Daily OHLCV is used for technical indicators.
    Realtime OHLCV is kept separately for execution decisions.
    """

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
        self._freshness_rule = DataFreshnessRule()
        self._logger = logger

    async def execute(
        self,
        stocks: list[Stock],
        status: PipelineStatus,
        indicators: IndicatorParameters,
    ) -> None:
        self._logger.info(f"Fetching OHLCV data for {len(stocks)} stocks.")
        history_by_stock_id = await self.fetch_history(stocks, status)

        if history_by_stock_id is None:
            return

        calculator = TechnicalIndicatorCalculator(indicators)
        collected_count = 0

        for stock in stocks:
            if self.apply_history(
                stock,
                history_by_stock_id,
                calculator,
                status,
            ):
                collected_count += 1

        self._logger.success(
            f"Collected market data for {collected_count}/{len(stocks)} stocks."
        )

    async def fetch_history(
        self,
        stocks: list[Stock],
        status: PipelineStatus,
    ) -> dict[str, list[Ohlcv]] | None:
        # TODO: move try catch to infra layer?
        try:
            start_date, end_date = self._market_clock.history_window(
                self._lookback_days
            )
            return await self._ohlcv_provider.fetch_history(
                stocks=stocks,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as error:
            message = f"Failed to fetch market data: {error}"
            self._logger.error(message)
            status.stats.add_error(message)
            return None

    def apply_history(
        self,
        stock: Stock,
        history_by_stock_id: dict[str, list[Ohlcv]],
        calculator: TechnicalIndicatorCalculator,
        status: PipelineStatus,
    ) -> bool:
        try:
            bars = history_by_stock_id.get(stock.stock_id, [])
            stock.ohlcv = list(bars)
            stock.indicators = TechnicalIndicators()
            stock.technical_report = None

            if not bars:
                self._logger.warning(
                    f"Market data unavailable: {stock.stock_id}"
                )
                return False

            stock.indicators = calculator.calculate(stock.ohlcv)
            return True

        except Exception as error:
            message = (
                f"Failed to process market data for "
                f"{stock.stock_id}: {error}"
            )
            self._logger.error(message)
            status.stats.add_error(message)
            return False

    async def refresh_realtime(
        self,
        stocks: list[Stock],
        status: PipelineStatus,
    ) -> None:
        unique_stocks = list(
            {stock.stock_id: stock for stock in stocks}.values()
        )
        current_time = self._market_clock.now()
        pending_stocks = [
            stock
            for stock in unique_stocks
            if self.needs_realtime_refresh(stock, current_time)
        ]

        if not pending_stocks:
            return

        try:
            realtime_bars = await self._ohlcv_provider.fetch_realtime_bars(
                pending_stocks
            )
        except Exception as error:
            message = f"Failed to fetch realtime market data: {error}"
            self._logger.error(message)
            status.stats.add_error(message)

            for stock in pending_stocks:
                self.mark_stale(
                    stock,
                    status,
                    "realtime fetch failed",
                )
            return

        current_time = self._market_clock.now()

        for stock in pending_stocks:
            self.apply_realtime_bar(
                stock,
                realtime_bars.get(stock.stock_id),
                current_time,
                status,
            )

    def needs_realtime_refresh(
        self,
        stock: Stock,
        current_time: datetime,
    ) -> bool:
        if stock.realtime_bar is None:
            return True

        return not self._freshness_rule.is_fresh(
            stock.realtime_bar.ts,
            current_time,
        )

    def apply_realtime_bar(
        self,
        stock: Stock,
        bar: Ohlcv | None,
        current_time: datetime,
        status: PipelineStatus,
    ) -> None:
        if bar is None:
            self.mark_stale(
                stock,
                status,
                "missing realtime bar",
            )
            return

        stock.realtime_bar = bar

        if not self._freshness_rule.is_fresh(bar.ts, current_time):
            self.mark_stale(
                stock,
                status,
                f"stale realtime bar: {bar.ts.isoformat()}",
            )
            return

        status.stale_stock_ids.discard(stock.stock_id)

    def mark_stale(
        self,
        stock: Stock,
        status: PipelineStatus,
        reason: str,
    ) -> None:
        if stock.stock_id not in status.stale_stock_ids:
            status.stats.stale_market_data_count += 1

        status.stale_stock_ids.add(stock.stock_id)
        message = f"Market data blocked: {stock.stock_id}, {reason}"
        status.stats.log(message)
        self._logger.warning(message)
