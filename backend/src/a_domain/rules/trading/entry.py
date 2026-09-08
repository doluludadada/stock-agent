from dataclasses import dataclass
from datetime import UTC, datetime

from icontract import ensure, invariant, require

from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.reason import ReasonRule
from a_domain.rules.trading.sizing import SizingRule
from a_domain.types.enums import SignalSource, TradeAction


# TODO: Might needa check this class.
@invariant(lambda self: 0 <= self.buy_threshold <= 100)
@dataclass(frozen=True)
class EntryRule:
    """
    Buy-side rule.

    Responsibilities:
    - no position -> decide BUY / HOLD
    - existing position -> decide ADD / HOLD
    """

    buy_threshold: int
    sizing_rule: SizingRule

    @require(lambda stock: stock.current_price is not None, "Entry decision requires a valid current price")
    @ensure(lambda result: result.quantity >= 0, "BUY signal quantity must be non-negative")
    @ensure(lambda result: result.action != TradeAction.BUY or result.quantity > 0, "BUY signal must have positive quantity")
    def decide(self, stock: Stock, account: Account, position: Position | None = None) -> TradeSignal:
        current_price = stock.current_price
        composite_score = stock.composite_score

        if current_price is None:
            raise ValueError("Entry decision requires a valid current price")

        if composite_score is None:
            raise ValueError("Entry decision requires a composite score")

        quantity = 0
        reason = ReasonRule.build_entry_hold(stock, "Score below buy threshold")

        if composite_score >= self.buy_threshold:
            quantity = self.sizing_rule.calculate(account=account, price=current_price)
            reason = ReasonRule.build_entry_hold(
                stock,
                "Insufficient cash or position size too small",
            )

        if quantity > 0:
            reason = ReasonRule.build_entry(stock)

        if quantity > 0 and position is not None:
            reason = f"ADD_POSITION | CurrentQty={position.quantity} | {reason}"

        return TradeSignal(
            stock_id=stock.stock_id,
            action=TradeAction.BUY if quantity > 0 else TradeAction.HOLD,
            price_at_signal=current_price,
            source=SignalSource.COMBINED,
            score=composite_score,
            reason=reason,
            quantity=quantity,
            generated_at=datetime.now(UTC),
        )
