from a_domain.model.system.stats import SystemStats
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.use_cases.collect.candidates import Candidates
from b_application.use_cases.collect.market_data import MarketData
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.process.selection import Selection
from b_application.use_cases.process.valuation import Valuation
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.monitoring import Monitoring


class Pipeline:
    def __init__(
        self,
        candidates: Candidates,
        market_data: MarketData,
        selection: Selection,
        news_feed: NewsFeed,
        valuation: Valuation,
        signals: Signals,
        reporting: Reporting,
        monitoring: Monitoring,
        logger: ILoggingProvider,
    ):
        self._candidates = candidates
        self._market_data = market_data
        self._selection = selection
        self._news_feed = news_feed
        self._valuation = valuation
        self._signals = signals
        self._reporting = reporting
        self._monitoring = monitoring
        self._logger = logger

    async def execute(self, manual_symbols: list[str] | None = None) -> SystemStats:
        stats = SystemStats()
        self._logger.info(">>> Intraday Pipeline Started")

        try:
            # 0. Check exits on existing positions
            exit_signals = await self._monitoring.execute()

            # 1. Select
            candidates = await self._candidates.execute(manual_symbols)
            stats.total_candidates = len(candidates)
            if not candidates:
                self._logger.info("No candidates selected")
                if exit_signals:
                    await self._reporting.execute(exit_signals)
                    stats.signals_generated = len(exit_signals)
                return stats

            # 2. Collect Prices
            candidates = await self._market_data.execute(candidates)
            if not candidates:
                self._logger.info("No price data available")
                if exit_signals:
                    await self._reporting.execute(exit_signals)
                    stats.signals_generated = len(exit_signals)
                return stats

            # 3. Filter
            survivors = self._selection.execute(candidates, is_intraday=True)
            stats.passed_technical = len(survivors)
            if not survivors:
                self._logger.info("No stocks survived technical filter")
                if exit_signals:
                    await self._reporting.execute(exit_signals)
                    stats.signals_generated = len(exit_signals)
                return stats

            # 4. Collect Articles
            survivors = await self._news_feed.execute(survivors)

            # 5. Analyze Sentiment (RAG)
            survivors = await self._valuation.execute(survivors)
            stats.ai_analyzed = len(survivors)

            # 6. Generate Signals (RAG)
            new_signals = await self._signals.execute(survivors)
            all_signals = exit_signals + new_signals
            stats.signals_generated = len(all_signals)

            # 7. Send Notifications
            if all_signals:
                sent_count = await self._reporting.execute(all_signals)
                stats.orders_submitted = sent_count

        except Exception as e:
            self._logger.exception(f"Pipeline crashed: {e}")
            stats.add_error(str(e))

        self._logger.info(f"<<< Pipeline Finished. Signals: {stats.signals_generated}")
        return stats
