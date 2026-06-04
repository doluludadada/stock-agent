from dataclasses import dataclass
from datetime import datetime

from a_domain.model.market.stock import Stock
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.action import ActionRule
from a_domain.rules.trading.reason import ReasonRule
from a_domain.types.enums import SignalSource, TradeAction


# TODO: No hard code here
@dataclass(frozen=True)
class ExitRule:
    """
    Sell-side rule.

    Responsibilities:
    - emergency stop-loss SELL
    - score-based SELL
    - otherwise HOLD

    AccountRiskCheck should call decide_stop_loss_only().
    Full DecisionRule should call decide().
    """

    stop_loss_pct: float
    action_rule: ActionRule
    reason_rule: ReasonRule

    def decide(self, stock: Stock, position: Position) -> TradeSignal:
        stop_loss_signal = self.decide_stop_loss_only(stock=stock, position=position)

        if stop_loss_signal.action == TradeAction.SELL:
            return stop_loss_signal

        current_price = self._require_current_price(stock)
        self._validate_position(stock=stock, position=position)

        action = self.action_rule.resolve(stock.combined_score)

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

    def decide_stop_loss_only(self, stock: Stock, position: Position) -> TradeSignal:
        current_price = self._require_current_price(stock)
        self._validate_position(stock=stock, position=position)

        stop_loss_price = self.stop_loss_price(position.average_cost)

        if current_price > stop_loss_price:
            return TradeSignal(
                stock_id=stock.stock_id,
                action=TradeAction.HOLD,
                price_at_signal=current_price,
                source=SignalSource.TECHNICAL,
                score=stock.combined_score,
                reason=self.reason_rule.build_exit_hold(
                    stock=stock,
                    position=position,
                    cause="Stop-loss not triggered",
                ),
                quantity=0,
                stop_loss_price=stop_loss_price,
                generated_at=datetime.now(),
            )

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

    def stop_loss_price(self, average_cost: float) -> float:
        if average_cost <= 0:
            return 0

        return average_cost * (1 - self.stop_loss_pct)

    def _require_current_price(self, stock: Stock) -> float:
        if stock.current_price is None:
            raise ValueError(f"Cannot decide exit without current price: {stock.stock_id}")

        return stock.current_price

    def _validate_position(self, stock: Stock, position: Position) -> None:
        if position.quantity <= 0:
            raise ValueError(f"Cannot decide exit with non-positive position quantity: {stock.stock_id}")
