from datetime import datetime

from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.action import ActionRule
from a_domain.rules.trading.reason import ReasonRule
from a_domain.rules.trading.sizing import SizingRule
from a_domain.types.enums import SignalSource, TradeAction


class DecisionRule:
    """Facade Rule: Orchestrates the creation of a TradeSignal."""

    def __init__(
        self,
        action_rule: ActionRule,
        reason_rule: ReasonRule,
        sizing_rule: SizingRule,
        total_capital: float,
        risk_pct: float,
    ):
        self._action_rule = action_rule
        self._reason_rule = reason_rule
        self._sizing_rule = sizing_rule
        self._capital = total_capital
        self._risk_pct = risk_pct

    def decide(self, stock: Stock) -> TradeSignal | None:
        if stock.current_price is None:
            return None

        action = self._action_rule.resolve(stock.combined_score)
        reason = self._reason_rule.build(stock)

        quantity = 0
        if action == TradeAction.BUY:
            quantity = self._sizing_rule.calculate_quantity(
                capital=self._capital,
                price=stock.current_price,
                risk_per_trade_pct=self._risk_pct,
            )

        return TradeSignal(
            stock_id=stock.stock_id,
            action=action,
            price_at_signal=stock.current_price,
            source=SignalSource.HYBRID,
            score=stock.combined_score,
            reason=reason,
            quantity=quantity,
            generated_at=datetime.now(),
        )
