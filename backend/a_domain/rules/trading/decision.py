# src\a_domain\rules\trading\decision.py
from datetime import datetime
from decimal import Decimal

from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.model.trading.signal import TradeSignal
from src.a_domain.rules.trading.action import ActionRule
from src.a_domain.rules.trading.reason import ReasonRule
from src.a_domain.rules.trading.sizing import SizingRule
from src.a_domain.types.enums import SignalAction, SignalSource


class DecisionRule:
    """
    Facade Rule: Orchestrates the creation of a TradeSignal.
    """

    def __init__(
        self,
        action_rule: ActionRule,
        reason_rule: ReasonRule,
        sizing_rule: SizingRule,  # Injected
        total_capital: Decimal,  # Config value injected at startup
        risk_pct: float,  # Config value injected at startup
    ):
        self._action_rule = action_rule
        self._reason_rule = reason_rule
        self._sizing_rule = sizing_rule
        self._capital = total_capital
        self._risk_pct = risk_pct

    def decide(self, context: AnalysisContext) -> TradeSignal | None:
        """
        Main entry point to convert Context -> Signal.
        """
        if context.current_price is None:
            return None

        # 1. Determine Action
        action = self._action_rule.resolve(context.combined_score)

        # 2. Build Reason
        reason = self._reason_rule.build(context)

        # 3. Calculate Quantity (Only for BUY)
        quantity = 0
        if action == SignalAction.BUY:
            quantity = self._sizing_rule.calculate_quantity(
                capital=self._capital, price=context.current_price, risk_per_trade_pct=self._risk_pct
            )

        return TradeSignal(
            stock_id=context.stock.stock_id,
            action=action,
            price_at_signal=context.current_price,
            source=SignalSource.HYBRID,
            score=context.combined_score,
            reason=reason,
            quantity=quantity,
            generated_at=datetime.now(),
        )
