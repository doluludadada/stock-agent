from dataclasses import dataclass
from datetime import datetime

from icontract import ensure, invariant, require

from a_domain.model.market.stock import Stock
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.reason import ReasonRule
from a_domain.types.enums import SignalSource, TradeAction


# TODO: No hard code here
@invariant(lambda self: 0 < self.stop_loss_pct < 1)
@invariant(lambda self: 0 <= self.sell_threshold <= 100)
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
    sell_threshold: int

    @require(lambda stock: stock.current_price is not None, "Exit decision requires a valid current price")
    @require(lambda position: position.quantity > 0, "Exit decision requires a positive position quantity")
    @ensure(lambda result: result.action != TradeAction.SELL or result.quantity > 0, "SELL signal must have positive quantity")
    def decide(self, stock: Stock, position: Position) -> TradeSignal:
        stop_loss_signal = self.decide_stop_loss_only(stock=stock, position=position)

        if stop_loss_signal.action == TradeAction.SELL:
            return stop_loss_signal

        current_price = stock.current_price

        if stock.combined_score <= self.sell_threshold:
            return TradeSignal(
                stock_id=stock.stock_id,
                action=TradeAction.SELL,
                price_at_signal=current_price,
                source=SignalSource.HYBRID,
                score=stock.combined_score,
                reason=ReasonRule.build_exit(
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
            reason=ReasonRule.build_exit_hold(
                stock=stock,
                position=position,
                cause="No sell condition met",
            ),
            quantity=0,
            generated_at=datetime.now(),
        )

    @require(lambda stock: stock.current_price is not None, "Exit decision requires a valid current price")
    @require(lambda position: position.quantity > 0, "Exit decision requires a positive position quantity")
    def decide_stop_loss_only(self, stock: Stock, position: Position) -> TradeSignal:
        current_price = stock.current_price

        stop_loss_price = self.stop_loss_price(position.average_cost)

        if current_price > stop_loss_price:
            return TradeSignal(
                stock_id=stock.stock_id,
                action=TradeAction.HOLD,
                price_at_signal=current_price,
                source=SignalSource.TECHNICAL,
                score=stock.combined_score,
                reason=ReasonRule.build_exit_hold(
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
            reason=ReasonRule.build_exit(
                stock=stock,
                position=position,
                cause="STOP_LOSS",
            ),
            quantity=position.quantity,
            stop_loss_price=stop_loss_price,
            generated_at=datetime.now(),
        )

    @require(lambda average_cost: average_cost > 0)
    @ensure(lambda result: result > 0)
    def stop_loss_price(self, average_cost: float) -> float:
        return average_cost * (1 - self.stop_loss_pct)
