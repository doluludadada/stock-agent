from dataclasses import dataclass
from datetime import datetime

from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.action import ActionRule
from a_domain.rules.trading.reason import ReasonRule
from a_domain.rules.trading.sizing import SizingRule
from a_domain.types.enums import SignalSource, TradeAction


@dataclass(frozen=True)
class EntryRule:
    """Decides whether a non-held stock should become a BUY signal."""

    action_rule: ActionRule
    sizing_rule: SizingRule
    reason_rule: ReasonRule

    def decide(self, stock: Stock, account: Account) -> TradeSignal | None:
        if stock.current_price is None:
            return None

        action = self.action_rule.resolve(stock.combined_score)
        if action != TradeAction.BUY:
            return None

        quantity = self.sizing_rule.calculate(account=account, price=stock.current_price)
        if quantity <= 0:
            return None

        return TradeSignal(
            stock_id=stock.stock_id,
            action=TradeAction.BUY,
            price_at_signal=stock.current_price,
            source=SignalSource.HYBRID,
            score=stock.combined_score,
            reason=self.reason_rule.build_entry(stock),
            quantity=quantity,
            generated_at=datetime.now(),
        )
