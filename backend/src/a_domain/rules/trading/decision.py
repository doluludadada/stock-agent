from collections.abc import Sequence, Set as AbstractSet
from dataclasses import dataclass
from datetime import datetime

from icontract import ensure, require

from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.entry import EntryRule
from a_domain.rules.trading.exit import ExitRule
from a_domain.rules.trading.sizing import BuyCostRule
from a_domain.types.enums import TradeAction


@dataclass(frozen=True)
class DecisionSkipRule:
    """
    The watchlist stocks that get no trading decision in this run, in watchlist order, each with why: the stop-loss
    check already sold it, its realtime quote is stale, or it has no composite score or no price.
    """

    def apply(
        self, stocks: Sequence[Stock], risk_blocked_stock_ids: AbstractSet[str], stale_stock_ids: AbstractSet[str]
    ) -> dict[str, str]:
        skipped: dict[str, str] = {}

        for stock in stocks:
            if stock.stock_id in risk_blocked_stock_ids:
                skipped[stock.stock_id] = "Risk blocked"
            elif stock.stock_id in stale_stock_ids:
                skipped[stock.stock_id] = "Market data is stale"
            elif stock.composite_score is None:
                skipped[stock.stock_id] = "Composite score unavailable"
            elif stock.current_price is None:
                skipped[stock.stock_id] = "No price"

        return skipped


@dataclass(frozen=True)
class DecisionRule:
    """
    Single source of truth for the final trading decision on one stock.

    - no position: EntryRule decides BUY or HOLD
    - a position: ExitRule decides SELL or HOLD; a technical hard failure keeps that HOLD;
      otherwise EntryRule may decide ADD or HOLD
    """

    entry_rule: EntryRule
    exit_rule: ExitRule

    @ensure(lambda result: len(result.stock_id) > 0, "Signal must have a stock_id")
    @ensure(lambda result: result.quantity >= 0, "Signal quantity must be non-negative")
    def apply(self, stock: Stock, account: Account, position: Position | None = None, *, now: datetime) -> TradeSignal:
        if position is None:
            return self.entry_rule.apply(stock=stock, account=account, now=now)

        exit_signal = self.exit_rule.apply(stock=stock, position=position, now=now)

        if exit_signal.action == TradeAction.SELL:
            return exit_signal

        if stock.is_eliminated:
            return exit_signal

        return self.entry_rule.apply(stock=stock, account=account, position=position, now=now)


@dataclass(frozen=True)
class RunDecisionsRule:
    """
    One run's decisions, best composite score first and a tie to the lower stock id. Each decision sees the cash
    the run's earlier BUYs left: their quantity at the order's limit plus the fee (BuyCostRule). So the BUYs of one
    run never commit more than the account's cash, and when the cash runs out the better-scored stocks have it.
    """

    decision_rule: DecisionRule
    buy_cost_rule: BuyCostRule

    @require(lambda stocks: all(stock.composite_score is not None for stock in stocks), "Every stock needs a composite score")
    @require(lambda stocks: len({stock.stock_id for stock in stocks}) == len(stocks), "One decision per stock")
    def apply(self, stocks: Sequence[Stock], account: Account, *, now: datetime) -> list[TradeSignal]:
        cash = account.cash
        signals: list[TradeSignal] = []

        for stock in sorted(stocks, key=lambda stock: (-(stock.composite_score or 0), stock.stock_id)):
            position = account.position_for(stock.stock_id)
            signal = self.decision_rule.apply(stock, account.model_copy(update={"cash": cash}), position, now=now)

            if signal.action == TradeAction.BUY:
                cash -= self.buy_cost_rule.apply(signal.stock_id, signal.price_at_signal, signal.quantity)

            signals.append(signal)

        return signals
