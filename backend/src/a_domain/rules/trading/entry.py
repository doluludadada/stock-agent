# backend/src/a_domain/rules/trading/entry.py

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
    """
    Decides BUY or HOLD for a non-held stock.
        - A non-held stock should never return None after analysis.
        - If it is not buyable, the explicit decision is HOLD.
    """

    action_rule: ActionRule
    """
    Converts combined_score into BUY / SELL / HOLD.
    For entry flow, only BUY becomes an orderable decision.
    """

    sizing_rule: SizingRule
    """
    Calculates BUY quantity from current usable cash and current stock price.
    """

    reason_rule: ReasonRule
    """
    Builds human-readable decision reasons for audit, notification, and RAG memory.
    """

    def decide(self, stock: Stock, account: Account) -> TradeSignal:
        current_price = stock.current_price
        """
        Entry decision needs a valid executable price.
        Upstream MarketData and TechnicalFilter should guarantee this.
        """

        if current_price is None:
            raise ValueError(f"Cannot decide entry without current price: {stock.stock_id}")

        action = self.action_rule.resolve(stock.combined_score)
        """
        Converts the combined technical + AI score into a trading action.
        """

        if action != TradeAction.BUY:
            return TradeSignal(
                stock_id=stock.stock_id,
                action=TradeAction.HOLD,
                price_at_signal=current_price,
                source=SignalSource.HYBRID,
                score=stock.combined_score,
                reason=self.reason_rule.build_entry_hold(
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
                source=SignalSource.HYBRID,
                score=stock.combined_score,
                reason=self.reason_rule.build_entry_hold(
                    stock=stock,
                    cause="Insufficient cash or position size too small",
                ),
                quantity=0,
                generated_at=datetime.now(),
            )

        return TradeSignal(
            stock_id=stock.stock_id,
            action=TradeAction.BUY,
            price_at_signal=current_price,
            source=SignalSource.HYBRID,
            score=stock.combined_score,
            reason=self.reason_rule.build_entry(stock),
            quantity=quantity,
            generated_at=datetime.now(),
        )
