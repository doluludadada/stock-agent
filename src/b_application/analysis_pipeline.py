from src.a_domain.model.system.stats import SystemStats
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.b_application.use_cases.collect.article_collector import ArticleCollector
from src.b_application.use_cases.collect.candidate_selector import CandidateSelector
from src.b_application.use_cases.collect.price_data_collector import PriceDataCollector
from src.b_application.use_cases.process.score_combiner import ScoreCombiner
from src.b_application.use_cases.process.sentiment_analyser import SentimentAnalyser
from src.b_application.use_cases.process.technical_analyser import TechnicalAnalyser
from src.b_application.use_cases.ship.notification_dispatcher import NotificationDispatcher
from src.b_application.use_cases.ship.signal_generator import SignalGenerator
from src.b_application.use_cases.ship.signal_persister import SignalPersister


class AnalysisPipeline:
    def __init__(
        self,
        candidate_selector: CandidateSelector,
        price_collector: PriceDataCollector,
        technical_analyzer: TechnicalAnalyser,
        article_collector: ArticleCollector,
        sentiment_analyzer: SentimentAnalyser,
        score_combiner: ScoreCombiner,
        signal_generator: SignalGenerator,
        signal_persister: SignalPersister,
        notification_dispatcher: NotificationDispatcher,
        logger: ILoggingProvider,
    ):
        self._selector = candidate_selector
        self._price_collector = price_collector
        self._tech_analyzer = technical_analyzer
        self._art_collector = article_collector
        self._sent_analyzer = sentiment_analyzer
        self._combiner = score_combiner
        self._signal_gen = signal_generator
        self._persister = signal_persister
        self._notifier = notification_dispatcher
        self._logger = logger

    async def execute(self, manual_symbols: list[str] | None = None) -> SystemStats:
        # 1. Init Stats
        stats = SystemStats()
        stats.log("Pipeline started.")
        self._logger.info(">>> Pipeline Started")

        try:
            # --- Stage 1: Select ---
            candidates = await self._selector.execute(manual_symbols)
            stats.total_candidates = len(candidates)

            if not candidates:
                stats.log("No candidates found. Exiting.")
                return stats

            # --- Stage 2: Collect Price ---
            # Returns Contexts (Data Structures)
            contexts = await self._price_collector.execute(candidates)

            # --- Stage 3: Technical Filter (Funnel) ---
            # Modifies Contexts (Sets failures or passes)
            contexts = self._tech_analyzer.execute(contexts)

            # Filter survivors for next stage
            survivors = [c for c in contexts if c.is_passed]  # AnalysisContext property
            stats.passed_technical = len(survivors)
            stats.log(f"Funnel: {stats.total_candidates} -> {stats.passed_technical} survivors.")

            if not survivors:
                return stats

            # --- Stage 4: Enrichment & AI ---
            survivors = await self._art_collector.execute(survivors)
            survivors = await self._sent_analyzer.execute(survivors)
            stats.ai_analyzed = len(survivors)

            # --- Stage 5: Decision ---
            survivors = self._combiner.execute(survivors)

            # Signal Generator now delegates to DecisionRule
            signals = self._signal_gen.execute(survivors)
            stats.signals_generated = len(signals)

            # --- Stage 6: Ship ---
            await self._persister.execute(signals)
            sent_count = await self._notifier.execute(signals)

            stats.log(f"Pipeline finished. Signals: {len(signals)}, Notifications: {sent_count}")

        except Exception as e:
            self._logger.error(f"Pipeline Error: {e}")
            stats.add_error(str(e))
            stats.log(f"Critical Error: {e}")

        return stats
