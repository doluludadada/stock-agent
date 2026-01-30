from src.a_domain.model.system.stats import SystemStats
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.b_application.use_cases.collect.article_collector import ArticleCollector
from src.b_application.use_cases.collect.candidate_selector import CandidateSelector
from src.b_application.use_cases.collect.price_data_collector import PriceDataCollector
from src.b_application.use_cases.process.filter_candidates import FilterCandidates
from src.b_application.use_cases.process.sentiment_analyser import SentimentAnalyser
from src.b_application.use_cases.ship.make_decision import MakeDecision
from src.b_application.use_cases.ship.notification_dispatcher import NotificationDispatcher
from src.b_application.use_cases.ship.signal_persister import SignalPersister


class Pipeline:
    """
    Phase 3: The Orchestrator.
    Connects the "Pipes" (Use Cases) to let data flow from Selection to Notification.
    No business logic here, only flow control.
    """

    def __init__(
        self,
        selector: CandidateSelector,
        price_collector: PriceDataCollector,
        filter_candidates: FilterCandidates,
        article_collector: ArticleCollector,
        sentiment_analyzer: SentimentAnalyser,
        decision_maker: MakeDecision,
        persister: SignalPersister, # TODO: Merge with make dcision file.
        notifier: NotificationDispatcher,
        logger: ILoggingProvider,
    ):
        self._selector = selector
        self._price_collector = price_collector
        self._filter = filter_candidates
        self._article_collector = article_collector
        self._sentiment = sentiment_analyzer
        self._decision_maker = decision_maker
        self._persister = persister
        self._notifier = notifier
        self._logger = logger

    async def execute(self, manual_symbols: list[str] | None = None) -> SystemStats:
        stats = SystemStats()
        self._logger.info(">>> Intraday Pipeline Started")

        try:
            # 1. Select (Sources: Repo/Manual)
            candidates = await self._selector.execute(manual_symbols)
            stats.total_candidates = len(candidates)
            if not candidates:
                return stats

            # 2. Collect Price (Realtime + History)
            # Returns initialized AnalysisContexts
            contexts = await self._price_collector.execute(candidates)

            # 3. Filter (Funnel)
            # Returns ONLY survivors
            survivors = self._filter.execute(contexts)
            stats.passed_technical = len(survivors)

            if not survivors:
                self._logger.info("No stocks survived technical filter.")
                return stats

            # 4. Enrich (Articles)
            survivors = await self._article_collector.execute(survivors)

            # 5. Analyze (AI)
            survivors = await self._sentiment.execute(survivors)
            stats.ai_analyzed = len(survivors)

            # 6. Decide (Signal)
            signals = self._decision_maker.execute(survivors)
            stats.signals_generated = len(signals)

            # 7. Ship (Persist & Notify)
            if signals:
                await self._persister.execute(signals)
                sent_count = await self._notifier.execute(signals)
                stats.orders_submitted = sent_count  # Using this field for notifications for now

        except Exception as e:
            self._logger.exception(f"Pipeline crashed: {e}")
            stats.add_error(str(e))

        self._logger.info(f"<<< Pipeline Finished. Signals: {stats.signals_generated}")
        return stats
