"""
Use Case: Generate and persist trade signals.

The final decision point - converts analyzed contexts into actionable signals.
"""
from backend.src.a_domain.model.analysis.analysis_context import AnalysisContext
from backend.src.a_domain.model.trading.signal import TradeSignal
from backend.src.a_domain.ports.analysis.signal_repository import ISignalRepository
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.a_domain.rules.process.scoring.composite import CompositeScoreRule
from backend.src.a_domain.rules.trading.decision import DecisionRule
from backend.src.a_domain.types.enums import AnalysisStage


class GenerateSignals:
    """
    The Final Judge.
    
    Combines technical and sentiment scores, applies trading rules,
    generates signals, and persists them.
    """

    def __init__(
        self,
        composite_rule: CompositeScoreRule,
        decision_rule: DecisionRule,
        signal_repo: ISignalRepository,
        logger: ILoggingProvider,
    ):
        self._composite_rule = composite_rule
        self._decision_rule = decision_rule
        self._signal_repo = signal_repo
        self._logger = logger

    async def execute(self, contexts: list[AnalysisContext]) -> list[TradeSignal]:
        """
        Generate signals from analyzed contexts and persist them.
        
        Returns:
            List of generated TradeSignals (for notification use).
        """
        self._logger.info(f"Generating signals for {len(contexts)} analyzed stocks...")
        signals: list[TradeSignal] = []

        for ctx in contexts:
            # 1. Calculate combined score
            ctx.combined_score = self._composite_rule.calculate(
                technical_score=ctx.technical_score,
                sentiment_score=ctx.sentiment_score,
            )
            ctx.stage = AnalysisStage.DECIDED

            # 2. Apply decision logic
            signal = self._decision_rule.decide(ctx)

            if signal:
                signals.append(signal)
                self._logger.info(
                    f"Signal: {signal.action} {signal.stock_id} "
                    f"(Score: {signal.score}, Qty: {signal.quantity})"
                )
            else:
                self._logger.trace(f"No signal for {ctx.stock.stock_id} (Score: {ctx.combined_score})")

        # 3. Persist all signals
        if signals:
            try:
                await self._signal_repo.save_batch(signals)
                self._logger.success(f"Persisted {len(signals)} signals")
            except Exception as e:
                self._logger.error(f"Failed to persist signals: {e}")

        return signals


