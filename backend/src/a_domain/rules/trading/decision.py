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

    No position means entry evaluation.
    Existing position means exit evaluation.
    """

    entry_rule: EntryRule
    exit_rule: ExitRule

    def decide(
        self,
        stock: Stock,
        account: Account,
        position: Position | None = None,
    ) -> TradeSignal | None:
        if position is not None:
            return self.exit_rule.decide(stock=stock, position=position)

        return self.entry_rule.decide(stock=stock, account=account)
