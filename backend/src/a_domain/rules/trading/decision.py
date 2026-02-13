from datetime import datetime
from decimal import Decimal

from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.model.trading.signal import TradeSignal
from backend.src.a_domain.rules.trading.action import ActionRule
from backend.src.a_domain.rules.trading.reason import ReasonRule
from backend.src.a_domain.rules.trading.sizing import SizingRule
from backend.src.a_domain.types.enums import SignalAction, SignalSource


class DecisionRule:
    """Facade Rule: Orchestrates the creation of a TradeSignal."""

    def __init__(
        self,
        action_rule: ActionRule,
        reason_rule: ReasonRule,
        sizing_rule: SizingRule,
        total_capital: Decimal,
        risk_pct: float,
    ):
        self._action_rule = action_rule
        self._reason_rule = reason_rule
        self._sizing_rule = sizing_rule
        self._capital = total_capital
        self._risk_pct = risk_pct

    def decide(self, candidate: Stock) -> TradeSignal | None:
        if candidate.current_price is None:
            return None

        action = self._action_rule.resolve(candidate.combined_score)
        reason = self._reason_rule.build(candidate)

        quantity = 0
        if action == SignalAction.BUY:
            quantity = self._sizing_rule.calculate_quantity(
                capital=self._capital,
                price=candidate.current_price,
                risk_per_trade_pct=self._risk_pct,
            )

        return TradeSignal(
            stock_id=candidate.stock_id,
            action=action,
            price_at_signal=candidate.current_price,
            source=SignalSource.HYBRID,
            score=candidate.combined_score,
            reason=reason,
            quantity=quantity,
            generated_at=datetime.now(),
        )
