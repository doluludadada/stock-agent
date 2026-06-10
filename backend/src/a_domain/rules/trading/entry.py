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
    sizing_rule: SizingRule #? it should be exit logic?

    @require(lambda stock: stock.current_price is not None, "Entry decision requires a valid current price")
    @ensure(lambda result: result.quantity >= 0, "BUY signal quantity must be non-negative")
    @ensure(lambda result: result.action != TradeAction.BUY or result.quantity > 0, "BUY signal must have positive quantity")
    def decide(
        self,
        stock: Stock,
        account: Account,
        position: Position | None = None,
    ) -> TradeSignal:
        current_price = stock.current_price

        if stock.combined_score < self.buy_threshold:
            return TradeSignal(
                stock_id=stock.stock_id,
                action=TradeAction.HOLD,
                price_at_signal=current_price,
                source=SignalSource.COMBINED,
                score=stock.combined_score,
                reason=ReasonRule.build_entry_hold(
                    stock=stock,
                    cause="Score below buy threshold",
                ),
                quantity=0,
                generated_at=datetime.now(),
            )

        quantity = self.sizing_rule.calculate(account=account, price=current_price)

        if quantity <= 0:
            return TradeSignal(
                stock_id=stock.stock_id,
                action=TradeAction.HOLD,
                price_at_signal=current_price,
                source=SignalSource.COMBINED,
                score=stock.combined_score,
                reason=ReasonRule.build_entry_hold(
                    stock=stock,
                    cause="Insufficient cash or position size too small",
                ),
                quantity=0,
                generated_at=datetime.now(),
            )

        reason = ReasonRule.build_entry(stock)

        if position is not None:
            reason = f"ADD_POSITION | CurrentQty={position.quantity} | {reason}"

        return TradeSignal(
            stock_id=stock.stock_id,
            action=TradeAction.BUY,
            price_at_signal=current_price,
            source=SignalSource.COMBINED,
            score=stock.combined_score,
            reason=reason,
            quantity=quantity,
            generated_at=datetime.now(),
        )
