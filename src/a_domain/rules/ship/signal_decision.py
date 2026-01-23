from datetime import datetime

from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.model.analysis.signal import TradeSignal
from src.a_domain.rules.ship.signal_action import SignalActionResolver
from src.a_domain.rules.ship.signal_reason_builder import SignalReasonBuilder
from src.a_domain.types.enums import SignalSource


class SignalDecisionRule:
    """
    Rule: Orchestrates signal generation by composing action resolution and reason building.
    No private methods - delegates to injected rules.
    """

    def __init__(
        self,
        action_resolver: SignalActionResolver,
        reason_builder: SignalReasonBuilder,
    ):
        self.action_resolver = action_resolver
        self.reason_builder = reason_builder

    def decide(self, context: AnalysisContext) -> TradeSignal | None:
        if context.combined_score is None or context.current_price is None:
            return None

        action = self.action_resolver.resolve(context.combined_score)
        reason = self.reason_builder.build(context)

        return TradeSignal(
            stock_id=context.stock.stock_id,
            action=action,
            price_at_signal=context.current_price,
            source=SignalSource.HYBRID,
            score=context.combined_score,
            reason=reason,
            generated_at=datetime.now(),
        )
