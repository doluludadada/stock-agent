from a_domain.model.system.stats import SystemStats
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.use_cases.collect.collect_articles import CollectArticles
from b_application.use_cases.collect.collect_prices import CollectPrices
from b_application.use_cases.collect.select_candidates import SelectCandidates
from b_application.use_cases.process.analyze_sentiment import AnalyzeSentiment
from b_application.use_cases.process.filter_candidates import FilterCandidates
from b_application.use_cases.ship.generate_signals import GenerateSignals
from b_application.use_cases.ship.send_notifications import SendNotifications
from b_application.use_cases.trade.check_portfolio_exits import CheckPortfolioExits


class Pipeline:
    def __init__(
        self,
        select_candidates: SelectCandidates,
        collect_prices: CollectPrices,
        filter_candidates: FilterCandidates,
        collect_articles: CollectArticles,
        analyze_sentiment: AnalyzeSentiment,
        generate_signals: GenerateSignals,
        send_notifications: SendNotifications,
        check_exits: CheckPortfolioExits,
        logger: ILoggingProvider,
    ):
        self._select = select_candidates
        self._prices = collect_prices
        self._filter = filter_candidates
        self._articles = collect_articles
        self._sentiment = analyze_sentiment
        self._signals = generate_signals
        self._notify = send_notifications
        self._check_exits = check_exits
        self._logger = logger

    async def execute(self, manual_symbols: list[str] | None = None) -> SystemStats:
        stats = SystemStats()
        self._logger.info(">>> Intraday Pipeline Started")

        try:
            # 0. Check exits on existing positions
            exit_signals = await self._check_exits.execute()

            # 1. Select
            candidates = await self._select.execute(manual_symbols)
            stats.total_candidates = len(candidates)
            if not candidates:
                self._logger.info("No candidates selected")
                if exit_signals:
                    await self._notify.execute(exit_signals)
                    stats.signals_generated = len(exit_signals)
                return stats

            # 2. Collect Prices
            candidates = await self._prices.execute(candidates)
            if not candidates:
                self._logger.info("No price data available")
                if exit_signals:
                    await self._notify.execute(exit_signals)
                    stats.signals_generated = len(exit_signals)
                return stats

            # 3. Filter
            survivors = self._filter.execute(candidates, is_intraday=True)
            stats.passed_technical = len(survivors)
            if not survivors:
                self._logger.info("No stocks survived technical filter")
                if exit_signals:
                    await self._notify.execute(exit_signals)
                    stats.signals_generated = len(exit_signals)
                return stats

            # 4. Collect Articles
            survivors = await self._articles.execute(survivors)

            # 5. Analyze Sentiment (RAG)
            survivors = await self._sentiment.execute(survivors)
            stats.ai_analyzed = len(survivors)

            # 6. Generate Signals (RAG)
            new_signals = await self._signals.execute(survivors)
            all_signals = exit_signals + new_signals
            stats.signals_generated = len(all_signals)

            # 7. Send Notifications
            if all_signals:
                sent_count = await self._notify.execute(all_signals)
                stats.orders_submitted = sent_count

        except Exception as e:
            self._logger.exception(f"Pipeline crashed: {e}")
            stats.add_error(str(e))

        self._logger.info(f"<<< Pipeline Finished. Signals: {stats.signals_generated}")
        return stats
