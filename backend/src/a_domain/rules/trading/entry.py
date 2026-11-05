from datetime import datetime

from pydantic.dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account, Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.reason import EntryReasonRule
from a_domain.rules.trading.sizing import SizingRule
from a_domain.types.enums import SignalSource, TradeAction
from a_domain.types.values import Score


@dataclass(frozen=True)
class EntryRule:
    """
    Buy-side rule: BUY or HOLD for a stock that is not held, ADD or HOLD for one that is.
    A BUY needs a composite score at or above `buy_threshold` and a quantity SizingRule can fit with the run's equity.
    """

    buy_threshold: Score[int]
    sizing_rule: SizingRule
    reason_rule: EntryReasonRule

    def apply(self, stock: Stock, account: Account, position: Position | None = None, *, equity: float, now: datetime) -> TradeSignal:
        current_price = stock.current_price
        composite_score = stock.composite_score

        if current_price is None or composite_score is None:
            raise ValueError("Entry decision requires a valid current price and a composite score")

        quantity = 0
        reason = self.reason_rule.apply(stock, hold_cause="Score below buy threshold")

        if composite_score >= self.buy_threshold:
            quantity = self.sizing_rule.apply(account=account, equity=equity, stock_id=stock.stock_id, price=current_price, now=now)
            reason = self.reason_rule.apply(stock, hold_cause="Insufficient cash or position size too small")

        if quantity > 0:
            reason = self.reason_rule.apply(stock, hold_cause=None)

        if quantity > 0 and position is not None:
            reason = f"ADD_POSITION | CurrentQty={position.quantity} | {reason}"

        action = TradeAction.BUY if quantity > 0 else TradeAction.HOLD

        return TradeSignal.of(
            stock, action=action, source=SignalSource.COMBINED, score=composite_score, reason=reason, quantity=quantity, now=now
        )


@dataclass(frozen=True)
class ManualEntryRule:
    """The user's confirmed BUY: it skips the buy threshold, never the sizing, and says why when no share fits."""

    sizing_rule: SizingRule

    def apply(self, stock: Stock, account: Account, *, equity: float, now: datetime) -> TradeSignal:
        current_price = stock.current_price
        composite_score = stock.composite_score

        if current_price is None or composite_score is None:
            raise ValueError("Manual BUY requires a current price and a composite score")

        quantity = self.sizing_rule.apply(account=account, equity=equity, stock_id=stock.stock_id, price=current_price, now=now)
        reason = "Manual BUY override confirmed by user."

        if quantity == 0:
            reason = (
                f"Manual BUY not sized: a {self.sizing_rule.risk_per_trade_pct:.0%} risk budget of equity {equity:,.0f}, "
                f"with cash {account.cash:,.0f} to pay, buys no share of {stock.stock_id} at {current_price:.2f} after fees."
            )

        action = TradeAction.BUY if quantity > 0 else TradeAction.HOLD

        return TradeSignal.of(
            stock, action=action, source=SignalSource.MANUAL, score=composite_score, reason=reason, quantity=quantity, now=now
        )
