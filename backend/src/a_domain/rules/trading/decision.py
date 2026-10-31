from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from icontract import ensure, require

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
        2. technical hard failure prevents adding to the position
        3. otherwise EntryRule may decide ADD / HOLD
    """

    entry_rule: EntryRule
    """
    Handles stocks that are not currently held.
    """

    exit_rule: ExitRule
    """
    Handles stocks that already have an open position.
    """

    @ensure(lambda result: len(result.stock_id) > 0, "Signal must have a stock_id")
    @ensure(lambda result: result.quantity >= 0, "Signal quantity must be non-negative")
    def decide(self, stock: Stock, account: Account, position: Position | None = None, *, now: datetime) -> TradeSignal:
        if position is None:
            return self.entry_rule.decide(stock=stock, account=account, now=now)

        exit_signal = self.exit_rule.decide(stock=stock, position=position, now=now)

        if exit_signal.action == TradeAction.SELL:
            return exit_signal

        if stock.is_eliminated:
            return exit_signal

        return self.entry_rule.decide(stock=stock, account=account, position=position, now=now)

    @require(lambda stocks: all(stock.composite_score is not None for stock in stocks), "Every stock needs a composite score")
    @require(lambda stocks: len({stock.stock_id for stock in stocks}) == len(stocks), "One decision per stock")
    def decide_run(self, stocks: Sequence[Stock], account: Account, *, now: datetime) -> list[TradeSignal]:
        """
        One run's decisions, best composite score first and a tie to the lower stock id. Each decision sees the cash
        the run's earlier BUYs left: their quantity at the order's limit plus the fee. So the BUYs of one run never
        commit more than the account's cash, and when the cash runs out the better-scored stocks have it.
        """
        cash = account.cash
        signals: list[TradeSignal] = []

        for stock in sorted(stocks, key=lambda stock: (-(stock.composite_score or 0), stock.stock_id)):
            signal = self.decide(stock, account.model_copy(update={"cash": cash}), account.position_for(stock.stock_id), now=now)

            if signal.action == TradeAction.BUY:
                cash -= self.entry_rule.sizing_rule.buy_cost(signal.stock_id, signal.price_at_signal, signal.quantity)

            signals.append(signal)

        return signals
