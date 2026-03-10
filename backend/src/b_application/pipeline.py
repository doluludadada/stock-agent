from a_domain.model.system.stats import SystemStats
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.use_cases.collect.market_data import MarketData
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.collect.stock_selector import StockSelector
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.monitoring import Monitoring
from b_application.use_cases.trade.order_execution import OrderExecution


class Pipeline:
    def __init__(
        self,
        stock_selector: StockSelector,
        market_data: MarketData,
        technical_filter: TechnicalFilter,
        news_feed: NewsFeed,
        ai_analyser: AiAnalyser,
        signals: Signals,
        order_execution: OrderExecution,
        reporting: Reporting,
        monitoring: Monitoring,
        logger: ILoggingProvider,
    ):
        self._stock_selector = stock_selector
        self._market_data = market_data
        self._technical_filter = technical_filter
        self._news_feed = news_feed
        self._ai_analyser = ai_analyser
        self._signals = signals
        self._order_execution = order_execution
        self._reporting = reporting
        self._monitoring = monitoring
        self._logger = logger

    async def execute(self, manual_symbols: list[str] | None = None) -> SystemStats:
        stats = SystemStats()
        self._logger.info(">>> Intraday Pipeline Started")

        try:
            # 0. Check exits on existing positions (Stop-Loss / Take-Profit)
            exit_signals = await self._monitoring.execute()

            # 1. Select stocks
            stocks = await self._stock_selector.execute(manual_symbols)
            stats.total_scanned = len(stocks)

            if not stocks:
                self._logger.info("No stocks selected.")
                if exit_signals:
                    stats.signals_generated = len(exit_signals)
                    stats.orders_submitted = await self._order_execution.execute(exit_signals)
                    await self._reporting.execute(exit_signals)
                return stats

            # 2. Collect prices
            stocks = await self._market_data.execute(stocks)
            if not stocks:
                self._logger.info("No price data available.")
                if exit_signals:
                    stats.signals_generated = len(exit_signals)
                    stats.orders_submitted = await self._order_execution.execute(exit_signals)
                    await self._reporting.execute(exit_signals)
                return stats

            # 3. Technical filter
            survivors = self._technical_filter.execute(stocks, is_intraday=True)
            stats.passed_technical = len(survivors)
            if not survivors:
                self._logger.info("No stocks survived the technical filter.")
                if exit_signals:
                    stats.signals_generated = len(exit_signals)
                    stats.orders_submitted = await self._order_execution.execute(exit_signals)
                    await self._reporting.execute(exit_signals)
                return stats

            # 4. Collect articles
            survivors = await self._news_feed.execute(survivors)

            # 5. Analyze fundamentals & news via AI
            survivors = await self._ai_analyser.execute(survivors)
            stats.ai_analyzed = len(survivors)

            # 6. Generate signals
            new_signals = await self._signals.execute(survivors)

            # Combine signals
            all_signals = exit_signals + new_signals
            stats.signals_generated = len(all_signals)

            if all_signals:
                # 7. Execute Orders
                executed_count = await self._order_execution.execute(all_signals)
                stats.orders_submitted = executed_count

                # 8. Send notifications
                await self._reporting.execute(all_signals)

        except Exception as e:
            self._logger.exception(f"Pipeline crashed: {e}")
            stats.add_error(str(e))

        self._logger.info(f"<<< Pipeline Finished. Orders Submitted: {stats.orders_submitted}")
        return stats
