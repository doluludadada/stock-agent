from dataclasses import dataclass
from datetime import datetime

from a_domain.model.market.stock import Stock
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.action import ActionRule
from a_domain.rules.trading.reason import ReasonRule
from a_domain.types.enums import SignalSource, TradeAction


@dataclass(frozen=True)
class ExitRule:
    """Decides whether a held position should become a SELL signal."""

    # Maximum tolerated loss from average cost.
    # Example: 0.1 means selling when price drops 10% below average cost.
    stop_loss_pct: float

    action_rule: ActionRule
    reason_rule: ReasonRule

    def decide(self, stock: Stock, position: Position) -> TradeSignal | None:
        if stock.current_price is None:
            return None

        if position.quantity <= 0:
            return None

        if self._should_stop_loss(stock.current_price, position.average_cost):
            return self._build_sell_signal(
                stock=stock,
                position=position,
                cause="STOP_LOSS",
                source=SignalSource.TECHNICAL,
                score=0,
            )

        action = self.action_rule.resolve(stock.combined_score)
        if action == TradeAction.SELL:
            return self._build_sell_signal(
                stock=stock,
                position=position,
                cause="SCORE_EXIT",
                source=SignalSource.HYBRID,
                score=stock.combined_score,
            )

        return None

    def _should_stop_loss(self, current_price: float, average_cost: float) -> bool:
        if average_cost <= 0:
            return False

        stop_loss_price = average_cost * (1.0 - self.stop_loss_pct)

        return current_price <= stop_loss_price

    def _build_sell_signal(
        self,
        stock: Stock,
        position: Position,
        cause: str,
        source: SignalSource,
        score: int,
    ) -> TradeSignal:
        return TradeSignal(
            stock_id=stock.stock_id,
            action=TradeAction.SELL,
            price_at_signal=stock.current_price,
            source=source,
            score=score,
            reason=self.reason_rule.build_exit(stock, position, cause),
            quantity=position.quantity,
            generated_at=datetime.now(),
        )
