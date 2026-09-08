from dataclasses import dataclass
from datetime import UTC, datetime

from icontract import ensure, invariant, require

from a_domain.model.market.stock import Stock
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.reason import ReasonRule
from a_domain.types.enums import SignalSource, TradeAction


# TODO: Needa check
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
        stop_loss_signal = self.decide_stop_loss_only(stock, position)

        if stop_loss_signal.action == TradeAction.SELL:
            return stop_loss_signal

        current_price = stock.current_price
        composite_score = stock.composite_score

        if current_price is None:
            raise ValueError("Exit decision requires a valid current price")

        if composite_score is None:
            raise ValueError("Exit decision requires a composite score")

        should_sell = composite_score <= self.sell_threshold
        action = TradeAction.SELL if should_sell else TradeAction.HOLD
        cause = "SCORE_EXIT" if should_sell else "No sell condition met"

        reason = ReasonRule.build_exit(stock, position, cause) if should_sell else ReasonRule.build_exit_hold(stock, position, cause)

        return TradeSignal(
            stock_id=stock.stock_id,
            action=action,
            price_at_signal=current_price,
            source=SignalSource.COMBINED,
            score=composite_score,
            reason=reason,
            quantity=position.quantity if should_sell else 0,
            generated_at=datetime.now(UTC),
        )

    @require(lambda stock: stock.current_price is not None, "Exit decision requires a valid current price")
    @require(lambda position: position.quantity > 0, "Exit decision requires a positive position quantity")
    def decide_stop_loss_only(self, stock: Stock, position: Position) -> TradeSignal:
        current_price = stock.current_price

        if current_price is None:
            raise ValueError("Stop-loss decision requires a valid current price")

        stop_loss_price = self.stop_loss_price(position.average_cost)
        should_sell = current_price <= stop_loss_price
        action = TradeAction.SELL if should_sell else TradeAction.HOLD
        cause = "STOP_LOSS" if should_sell else "Stop-loss not triggered"

        reason = ReasonRule.build_exit(stock, position, cause) if should_sell else ReasonRule.build_exit_hold(stock, position, cause)

        return TradeSignal(
            stock_id=stock.stock_id,
            action=action,
            price_at_signal=current_price,
            source=SignalSource.TECHNICAL,
            score=stock.technical_score or 0,
            reason=reason,
            quantity=position.quantity if should_sell else 0,
            stop_loss_price=stop_loss_price,
            generated_at=datetime.now(UTC),
        )

    @require(lambda average_cost: average_cost > 0)
    @ensure(lambda result: result > 0)
    def stop_loss_price(self, average_cost: float) -> float:
        return average_cost * (1 - self.stop_loss_pct)
