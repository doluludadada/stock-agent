# backend/src/a_domain/rules/trading/exit.py

from dataclasses import dataclass
from datetime import datetime

from a_domain.model.market.stock import Stock
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.action import ActionRule
from a_domain.rules.trading.reason import ReasonRule
from a_domain.types.enums import SignalSource, TradeAction


# TODO: No hardcode here
@dataclass(frozen=True)
class ExitRule:
    """
    Decides SELL or HOLD for a held position.
        - Held positions must not disappear from decision output.
        - If there is no exit trigger, the explicit decision is HOLD.
    """

    stop_loss_pct: float
    """
    Maximum tolerated loss from average cost.
    Example: 0.1 means SELL when price drops 10% below average cost.
    """

    action_rule: ActionRule
    """
    Converts combined_score into BUY / SELL / HOLD.
    For exit flow, SELL becomes an orderable exit decision.
    """

    reason_rule: ReasonRule
    """
    Builds readable exit/HOLD reasons for audit, notification, and RAG memory.
    """

    def decide(self, stock: Stock, position: Position) -> TradeSignal:
        current_price = stock.current_price
        """
        Exit decision needs a valid executable price.
        """

        if current_price is None:
            raise ValueError(f"Cannot decide exit without current price: {stock.stock_id}")

        if position.quantity <= 0:
            raise ValueError(f"Cannot decide exit with non-positive position quantity: {stock.stock_id}")

        if self._should_stop_loss(current_price, position.average_cost):
            stop_loss_price = self._stop_loss_price(position.average_cost)

            return TradeSignal(
                stock_id=stock.stock_id,
                action=TradeAction.SELL,
                price_at_signal=current_price,
                source=SignalSource.TECHNICAL,
                score=0,
                reason=self.reason_rule.build_exit(
                    stock=stock,
                    position=position,
                    cause="STOP_LOSS",
                ),
                quantity=position.quantity,
                stop_loss_price=stop_loss_price,
                generated_at=datetime.now(),
            )

        action = self.action_rule.resolve(stock.combined_score)
        """
        Score-based exit uses the same final combined score as entry.
        """

        if action == TradeAction.SELL:
            return TradeSignal(
                stock_id=stock.stock_id,
                action=TradeAction.SELL,
                price_at_signal=current_price,
                source=SignalSource.HYBRID,
                score=stock.combined_score,
                reason=self.reason_rule.build_exit(
                    stock=stock,
                    position=position,
                    cause="SCORE_EXIT",
                ),
                quantity=position.quantity,
                generated_at=datetime.now(),
            )

        return TradeSignal(
            stock_id=stock.stock_id,
            action=TradeAction.HOLD,
            price_at_signal=current_price,
            source=SignalSource.HYBRID,
            score=stock.combined_score,
            reason=self.reason_rule.build_exit_hold(
                stock=stock,
                position=position,
                cause="No sell condition met",
            ),
            quantity=0,
            generated_at=datetime.now(),
        )

    def _should_stop_loss(self, current_price: float, average_cost: float) -> bool:
        """
        Checks whether current price has crossed the configured stop-loss line.

        Reason:
        Stop-loss is a hard exit rule and should be evaluated before score-based exit.
        """
        if average_cost <= 0:
            return False

        return current_price <= self._stop_loss_price(average_cost)

    def _stop_loss_price(self, average_cost: float) -> float:
        """
        Calculates the stop-loss trigger price.

        Reason:
        TradeSignal can store this value for audit and reporting.
        """
        return average_cost * (1.0 - self.stop_loss_pct)
