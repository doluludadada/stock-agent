# backend/src/a_domain/rules/trading/decision.py

from dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.entry import EntryRule
from a_domain.rules.trading.exit import ExitRule


@dataclass(frozen=True)
class DecisionRule:
    """
    Routes a stock to entry or exit decision.
    - The domain decision must always produce a TradeSignal:
        - BUY for executable entry
        - SELL for executable exit
        - HOLD for analysed but non-actionable decision
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
        """
        Produces exactly one final decision.

        Reason:
        None is not a valid decision because TradeAction.HOLD already exists.
        """
        if position is not None:
            return self.exit_rule.decide(stock=stock, position=position)

        return self.entry_rule.decide(stock=stock, account=account)
