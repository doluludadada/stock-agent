from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.model.trading.signal import TradeSignal
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.a_domain.rules.process.scoring.composite import CompositeScoreRule
from src.a_domain.rules.trading.decision import DecisionRule
from src.a_domain.types.enums import AnalysisStage


class MakeDecision:
    """
    Use Case: The Final Judge.
    Combines scores and applies trading rules to generate actionable signals.
    """

    def __init__(
        self,
        composite_rule: CompositeScoreRule,
        decision_rule: DecisionRule,
        logger: ILoggingProvider,
    ):
        self._composite_rule = composite_rule
        self._decision_rule = decision_rule
        self._logger = logger

    def execute(self, contexts: list[AnalysisContext]) -> list[TradeSignal]:
        self._logger.info(f"Making decisions for {len(contexts)} analyzed stocks...")
        signals: list[TradeSignal] = []

        for ctx in contexts:
            # 1. Calculate Combined Score
            ctx.combined_score = self._composite_rule.calculate(
                technical_score=ctx.technical_score, sentiment_score=ctx.sentiment_score
            )
            ctx.stage = AnalysisStage.DECIDED

            # 2. Apply Decision Logic (Action, Sizing, Reason)
            signal = self._decision_rule.decide(ctx)

            if signal:
                signals.append(signal)
                self._logger.info(f"Generated Signal: {signal.action} {signal.stock_id} (Score: {signal.score})")
            else:
                self._logger.trace(f"No signal for {ctx.stock.stock_id} (Score: {ctx.combined_score})")

        return signals
