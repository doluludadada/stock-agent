from collections.abc import Sequence, Set as AbstractSet
from dataclasses import dataclass
from datetime import datetime

from icontract import ensure, require

from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.entry import EntryRule
from a_domain.rules.trading.exit import BlockedStockRule, ExitRule
from a_domain.rules.trading.sizing import BuyCostRule
from a_domain.types.enums import SkipReason, TradeAction


@dataclass(frozen=True)
class DecisionSkipRule:
    """
    Why a watchlist stock gets no trading decision in this run, or None: BlockedStockRule blocks it, or it has no
    composite score or no price.
    """

    blocked_rule: BlockedStockRule

    def apply(self, stock: Stock, risk_blocked_stock_ids: AbstractSet[str], stale_stock_ids: AbstractSet[str]) -> SkipReason | None:
        blocked = self.blocked_rule.apply(stock, risk_blocked_stock_ids, stale_stock_ids)

        if blocked is not None:
            return blocked

        if stock.composite_score is None:
            return SkipReason.NO_COMPOSITE_SCORE

        if stock.current_price is None:
            return SkipReason.NO_PRICE

        return None


@dataclass(frozen=True)
class DecisionCandidatesRule:
    """
    The stocks Intraday decides on, each once: every technical survivor, then every other held stock that got a
    technical verdict, so a position that fails the strategy still has its exit decided.
    """

    def apply(self, technical_candidates: Sequence[Stock], survivors: Sequence[Stock], account: Account) -> list[Stock]:
        held = [stock for stock in technical_candidates if account.position_for(stock.stock_id) is not None]

        return list({stock.stock_id: stock for stock in [*survivors, *held]}.values())


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
    def apply(self, stock: Stock, account: Account, position: Position | None = None, *, equity: float, now: datetime) -> TradeSignal:
        if position is None:
            return self.entry_rule.apply(stock=stock, account=account, equity=equity, now=now)

        exit_signal = self.exit_rule.apply(stock=stock, position=position, now=now)

        if exit_signal.action == TradeAction.SELL:
            return exit_signal

        if stock.is_eliminated:
            return exit_signal

        return self.entry_rule.apply(stock=stock, account=account, position=position, equity=equity, now=now)


@dataclass(frozen=True)
class RunDecisionsRule:
    """
    One run's decisions, best composite score first and a tie to the lower stock id. Every BUY takes its risk budget
    from the same `equity`, fixed before the run's first decision, and is capped by the cash the run's earlier BUYs
    left: their quantity at the order's limit plus the fee (BuyCostRule). So the BUYs of one run never commit more than
    the account's cash, and when the cash runs out the better-scored stocks have it.
    """

    decision_rule: DecisionRule
    buy_cost_rule: BuyCostRule

    @require(lambda stocks: all(stock.composite_score is not None for stock in stocks), "Every stock needs a composite score")
    @require(lambda stocks: len({stock.stock_id for stock in stocks}) == len(stocks), "One decision per stock")
    def apply(self, stocks: Sequence[Stock], account: Account, equity: float, *, now: datetime) -> list[TradeSignal]:
        cash = account.cash
        signals: list[TradeSignal] = []

        for stock in sorted(stocks, key=lambda stock: (-(stock.composite_score or 0), stock.stock_id)):
            position = account.position_for(stock.stock_id)
            signal = self.decision_rule.apply(stock, account.model_copy(update={"cash": cash}), position, equity=equity, now=now)

            if signal.action == TradeAction.BUY:
                cash -= self.buy_cost_rule.apply(signal.stock_id, signal.price_at_signal, signal.quantity, now=now)

            signals.append(signal)

        return signals
