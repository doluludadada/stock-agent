import time
from datetime import datetime

from src.a_domain.model.analysis.pipeline_result import PipelineResult
from src.a_domain.model.analysis.signal import TradeSignal
from src.a_domain.ports.system.logging_port import ILoggingPort
from src.a_domain.types.enums import MarketType
from src.b_application.configuration.schemas import AppConfig
from src.b_application.use_cases.collect.article_collector import ArticleCollector
from src.b_application.use_cases.collect.market_scanner import MarketScanner
from src.b_application.use_cases.collect.price_data_collector import PriceDataCollector
from src.b_application.use_cases.process.score_combiner import ScoreCombiner
from src.b_application.use_cases.process.sentiment_analyser import SentimentAnalyser
from src.b_application.use_cases.process.technical_analyser import TechnicalAnalyser
from src.b_application.use_cases.ship.notification_dispatcher import NotificationDispatcher
from src.b_application.use_cases.ship.signal_generator import SignalGenerator
from src.b_application.use_cases.ship.signal_persister import SignalPersister


class AnalysisPipeline:
    """
    Main orchestrator for stock analysis pipeline.

    Flow: Collect -> Process -> Ship

    Collect Stage:
        1. MarketScanner: Get candidate stocks
        2. PriceDataCollector: Fetch OHLCV history
        3. ArticleCollector: Fetch and filter articles

    Process Stage:
        4. TechnicalAnalyzer: Compute indicators + screening
        5. SentimentAnalyzer: AI analysis of articles
        6. ScoreCombiner: Weighted combination

    Ship Stage:
        7. SignalGenerator: Create TradeSignal entities
        8. SignalPersister: Save to repository
        9. NotificationDispatcher: Alert users
    """

    def __init__(
        self,
        market_scanner: MarketScanner,
        price_collector: PriceDataCollector,
        article_collector: ArticleCollector,
        technical_analyzer: TechnicalAnalyser,
        sentiment_analyzer: SentimentAnalyser,
        score_combiner: ScoreCombiner,
        signal_generator: SignalGenerator,
        signal_persister: SignalPersister,
        notification_dispatcher: NotificationDispatcher,
        config: AppConfig,
        logger: ILoggingPort,
    ):
        # Collect stage
        self._market_scanner = market_scanner
        self._price_collector = price_collector
        self._article_collector = article_collector

        # Process stage
        self._technical_analyzer = technical_analyzer
        self._sentiment_analyzer = sentiment_analyzer
        self._score_combiner = score_combiner

        # Ship stage
        self._signal_generator = signal_generator
        self._signal_persister = signal_persister
        self._notification_dispatcher = notification_dispatcher

        self._config = config
        self._logger = logger

    async def execute(
        self,
        symbols: list[str] | None = None,
        markets: list[MarketType] | None = None,
    ) -> PipelineResult:
        """
        Execute the full analysis pipeline.

        Args:
            symbols: Specific stock symbols to analyze. None = scan all available.
            markets: Market types to include. None = all supported markets.

        Returns:
            PipelineResult with generated signals and execution metadata.
        """
        start_time = time.perf_counter()
        errors: list[str] = []

        self._logger.info("=" * 60)
        self._logger.info("Starting Analysis Pipeline")
        self._logger.info(f"Symbols: {symbols or 'ALL'}, Markets: {markets or 'ALL'}")
        self._logger.info("=" * 60)

        # ========== COLLECT STAGE ==========
        self._logger.info("[STAGE 1/3] COLLECT")

        try:
            stocks = await self._market_scanner.execute(symbols=symbols, markets=markets)
        except Exception as e:
            errors.append(f"MarketScanner failed: {e}")
            self._logger.error(str(e))
            return self._create_result([], 0, 0, start_time, errors)

        if not stocks:
            self._logger.warning("No stocks to analyze after scanning")
            return self._create_result([], 0, 0, start_time, errors)

        total_scanned = len(stocks)

        contexts = await self._price_collector.execute(stocks)
        contexts = await self._article_collector.execute(contexts)

        # ========== PROCESS STAGE ==========
        self._logger.info("[STAGE 2/3] PROCESS")

        # Technical analysis (sync)
        contexts = self._technical_analyzer.execute(contexts)

        # Filter to only stocks that passed technical screening
        passed_screening = [c for c in contexts if c.screening_result and c.screening_result.passed]
        passed_count = len(passed_screening)

        self._logger.info(f"Stocks passing technical screening: {passed_count}/{len(contexts)}")

        # Sentiment analysis only on stocks that passed (async)
        if passed_screening:
            passed_screening = await self._sentiment_analyzer.execute(passed_screening)

        # Combine scores (sync)
        passed_screening = self._score_combiner.execute(passed_screening)

        # ========== SHIP STAGE ==========
        self._logger.info("[STAGE 3/3] SHIP")

        # Generate signals (sync)
        signals = self._signal_generator.execute(passed_screening)

        # Persist signals (async)
        try:
            await self._signal_persister.execute(signals)
        except Exception as e:
            errors.append(f"SignalPersister failed: {e}")
            self._logger.error(str(e))

        # Dispatch notifications (async)
        try:
            await self._notification_dispatcher.execute(signals)
        except Exception as e:
            errors.append(f"NotificationDispatcher failed: {e}")
            self._logger.error(str(e))

        # ========== COMPLETE ==========
        result = self._create_result(signals, total_scanned, passed_count, start_time, errors)

        self._logger.info("=" * 60)
        self._logger.success(f"Pipeline complete. {len(signals)} signals generated in {result.execution_time_ms}ms")
        self._logger.info("=" * 60)

        return result

    def _create_result(
        self,
        signals: list[TradeSignal],
        total_scanned: int,
        passed_screening: int,
        start_time: float,
        errors: list[str],
    ) -> PipelineResult:
        """Create pipeline result with timing."""
        execution_time_ms = int((time.perf_counter() - start_time) * 1000)
        return PipelineResult(
            signals=tuple(signals),
            total_scanned=total_scanned,
            passed_screening=passed_screening,
            execution_time_ms=execution_time_ms,
            executed_at=datetime.now(),
            errors=tuple(errors),
        )
