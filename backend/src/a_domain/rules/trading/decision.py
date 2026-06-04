from dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.entry import EntryRule
from a_domain.rules.trading.exit import ExitRule
from a_domain.types.enums import TradeAction


@dataclass(frozen=True)
class DecisionRule:
    """
    Single source of truth for final trading decision.

    Flow:
    - no position -> EntryRule decides BUY / HOLD
    - existing position:
        1. ExitRule decides SELL / HOLD
        2. if not SELL, EntryRule may decide ADD / HOLD
    """

    entry_rule: EntryRule
    """
    Handles stocks that are not currently held.
    """
    exit_rule: ExitRule
    """
    Handles stocks that already have an open position.
    """

    def decide(
        self,
        stock: Stock,
        account: Account,
        position: Position | None = None,
    ) -> TradeSignal:
    
        if position is None:
            return self.entry_rule.decide(stock=stock, account=account)

        exit_signal = self.exit_rule.decide(stock=stock, position=position)

        if exit_signal.action == TradeAction.SELL:
            return exit_signal

        return self.entry_rule.decide(
            stock=stock,
            account=account,
            position=position,
        )
