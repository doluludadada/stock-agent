from dataclasses import dataclass
from datetime import datetime

from icontract import ensure, invariant, require

from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.reason import ReasonRule
from a_domain.rules.trading.sizing import SizingRule
from a_domain.types.enums import SignalSource, TradeAction


@invariant(lambda self: 0 <= self.buy_threshold <= 100)
@dataclass(frozen=True)
class EntryRule:
    """
    Buy-side rule.

    Responsibilities:
    - no position -> decide BUY / HOLD
    - existing position -> decide ADD / HOLD
    - manual override -> BUY sized like any other, or HOLD saying why no quantity fits
    """

    buy_threshold: int
    sizing_rule: SizingRule

    @require(lambda stock: stock.current_price is not None, "Entry decision requires a valid current price")
    @ensure(lambda result: result.quantity >= 0, "BUY signal quantity must be non-negative")
    @ensure(lambda result: result.action != TradeAction.BUY or result.quantity > 0, "BUY signal must have positive quantity")
    def decide(self, stock: Stock, account: Account, position: Position | None = None, *, now: datetime) -> TradeSignal:
        current_price = stock.current_price
        composite_score = stock.composite_score

        if current_price is None:
            raise ValueError("Entry decision requires a valid current price")

        if composite_score is None:
            raise ValueError("Entry decision requires a composite score")

        quantity = 0
        reason = ReasonRule.build_entry_hold(stock, "Score below buy threshold")

        if composite_score >= self.buy_threshold:
            quantity = self.sizing_rule.calculate(account=account, stock_id=stock.stock_id, price=current_price)
            reason = ReasonRule.build_entry_hold(stock, "Insufficient cash or position size too small")

        if quantity > 0:
            reason = ReasonRule.build_entry(stock)

        if quantity > 0 and position is not None:
            reason = f"ADD_POSITION | CurrentQty={position.quantity} | {reason}"

        return TradeSignal.of(
            stock,
            action=TradeAction.BUY if quantity > 0 else TradeAction.HOLD,
            source=SignalSource.COMBINED,
            score=composite_score,
            reason=reason,
            quantity=quantity,
            now=now,
        )

    @require(lambda stock: stock.current_price is not None, "Manual BUY requires a current price")
    @require(lambda stock: stock.composite_score is not None, "Manual BUY requires a composite score")
    @ensure(lambda result: result.source == SignalSource.MANUAL)
    def decide_manual(self, stock: Stock, account: Account, *, now: datetime) -> TradeSignal:
        """The user's BUY: skips the buy threshold, never the sizing."""
        current_price = stock.current_price
        composite_score = stock.composite_score

        if current_price is None or composite_score is None:
            raise ValueError("Manual BUY requires a current price and a composite score")

        quantity = self.sizing_rule.calculate(account=account, stock_id=stock.stock_id, price=current_price)
        reason = "Manual BUY override confirmed by user."

        if quantity == 0:
            reason = (
                f"Manual BUY not sized: cash {account.cash:,.0f} buys no share of {stock.stock_id} at {current_price:.2f} "
                f"within a {self.sizing_rule.risk_per_trade_pct:.0%} risk budget after fees."
            )

        return TradeSignal.of(
            stock,
            action=TradeAction.BUY if quantity > 0 else TradeAction.HOLD,
            source=SignalSource.MANUAL,
            score=composite_score,
            reason=reason,
            quantity=quantity,
            now=now,
        )
