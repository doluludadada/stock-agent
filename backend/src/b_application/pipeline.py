"""
Intraday Pipeline: The Orchestrator.

Connects use cases to let data flow from selection to notification.
No business logic here - only flow control.
"""
from backend.src.a_domain.model.system.stats import SystemStats
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.b_application.use_cases.collect.collect_articles import CollectArticles
from backend.src.b_application.use_cases.collect.collect_prices import CollectPrices
from backend.src.b_application.use_cases.collect.select_candidates import SelectCandidates
from backend.src.b_application.use_cases.process.analyze_sentiment import AnalyzeSentiment
from backend.src.b_application.use_cases.process.filter_candidates import FilterCandidates
from backend.src.b_application.use_cases.ship.generate_signals import GenerateSignals
from backend.src.b_application.use_cases.ship.send_notifications import SendNotifications


class Pipeline:
    """
    Intraday Pipeline Orchestrator.
    
    Flow:
    1. Select candidates from watchlists
    2. Collect real-time prices
    3. Filter through technical rules (with entry timing)
    4. Collect articles for survivors
    5. Analyze sentiment with AI
    6. Generate and persist signals
    7. Send notifications
    
    This class only orchestrates - all business logic lives in use cases.
    """

    def __init__(
        self,
        select_candidates: SelectCandidates,
        collect_prices: CollectPrices,
        filter_candidates: FilterCandidates,
        collect_articles: CollectArticles,
        analyze_sentiment: AnalyzeSentiment,
        generate_signals: GenerateSignals,
        send_notifications: SendNotifications,
        logger: ILoggingProvider,
    ):
        self._select = select_candidates
        self._prices = collect_prices
        self._filter = filter_candidates
        self._articles = collect_articles
        self._sentiment = analyze_sentiment
        self._signals = generate_signals
        self._notify = send_notifications
        self._logger = logger

    async def execute(self, manual_symbols: list[str] | None = None) -> SystemStats:
        """
        Execute the full intraday pipeline.
        
        Args:
            manual_symbols: Optional list of stock IDs to analyze manually.
            
        Returns:
            SystemStats with pipeline execution metrics.
        """
        stats = SystemStats()
        self._logger.info(">>> Intraday Pipeline Started")

        try:
            # 1. Select
            contexts = await self._select.execute(manual_symbols)
            stats.total_candidates = len(contexts)
            if not contexts:
                self._logger.info("No candidates selected")
                return stats

            # 2. Collect Prices
            contexts = await self._prices.execute(contexts)
            if not contexts:
                self._logger.info("No price data available")
                return stats

            # 3. Filter (with entry timing rules for intraday)
            survivors = self._filter.execute(contexts, is_intraday=True)
            stats.passed_technical = len(survivors)
            if not survivors:
                self._logger.info("No stocks survived technical filter")
                return stats

            # 4. Collect Articles
            survivors = await self._articles.execute(survivors)

            # 5. Analyze Sentiment
            survivors = await self._sentiment.execute(survivors)
            stats.ai_analyzed = len(survivors)

            # 6. Generate Signals (includes persistence)
            signals = await self._signals.execute(survivors)
            stats.signals_generated = len(signals)

            # 7. Send Notifications
            if signals:
                sent_count = await self._notify.execute(signals)
                stats.orders_submitted = sent_count

        except Exception as e:
            self._logger.exception(f"Pipeline crashed: {e}")
            stats.add_error(str(e))

        self._logger.info(f"<<< Pipeline Finished. Signals: {stats.signals_generated}")
        return stats


