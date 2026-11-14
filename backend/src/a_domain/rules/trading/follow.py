from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence, Sized
from dataclasses import replace
from datetime import date, datetime

from pydantic import ConfigDict, Field, PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account, AccountOpening, Position
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.cost import AffordableQuantityRule
from a_domain.rules.trading.ranking import Ranking, RankingHistory
from a_domain.rules.trading.tick import LimitPriceRule
from a_domain.types.enums import FollowRefusal, OrderPricing, SignalSource, TradeAction, TradingPhase
from a_domain.types.values import NonEmptyText


@dataclass(frozen=True)
class OpenDecisionsRule:
    """
    The decisions of `run` a follow may still take: its BUYs, and its SELLs of a stock the account holds now, when the
    run is a finished run of a followable workflow, but each one a follow order of which filled, in full or in part,
    since the mock account opened, and only the first of a stock's, so a follow places at most one order per stock. A
    refused or unsent follow, or one before the account's last reset, leaves the decision open.
    """

    def apply(
        self, run: SystemStats, decisions: Sequence[TradeSignal], follows: Sequence[tuple[TradeSignal, Order]], account: Account
    ) -> list[TradeSignal]:
        if not run.workflow.followable or run.end_time is None or run.failure is not None:
            return []

        followed = {
            follow.followed_decision_id
            for follow, order in follows
            if order.filled_quantity > 0 and (account.opened_at is None or order.created_at >= account.opened_at)
        }
        open_decisions: dict[str, TradeSignal] = {}

        for decision in decisions:
            held = decision.stock_id in account.stock_ids
            orderable = decision.action == TradeAction.BUY or (decision.action == TradeAction.SELL and held)

            if orderable and decision.decision_id not in followed:
                open_decisions.setdefault(decision.stock_id, decision)

        return list(open_decisions.values())


@dataclass(frozen=True)
class FollowWindowRule:
    """
    Why what a follow would take, a run's open decisions or the stocks a ranking follow trades, cannot be followed in
    the market's phase now, or None when a follow may start.
    """

    pricing: OrderPricing

    def apply(self, open_decisions: Sized, phase: TradingPhase) -> FollowRefusal | None:
        if not open_decisions:
            return FollowRefusal.NOTHING_TO_FOLLOW

        if phase != self.pricing.trading_phase:
            return FollowRefusal.OUTSIDE_FOLLOW_WINDOW

        return None


@dataclass(frozen=True)
class FollowRule:
    """
    The follow decision of one open decision at `now`, or why it gets none now and stays open. It keeps the decision's
    stock, action, score, reason and stop, takes the stock's current price, and names the decision it follows. A BUY
    keeps its shares; a SELL sells at most the shares held now, and nothing when none are held. The order gates judge
    the price when the order is placed.
    """

    def apply(self, decision: TradeSignal, stock: Stock | None, held: Position | None, now: datetime) -> TradeSignal | str:
        if decision.action == TradeAction.SELL and held is None:
            return "not held now"

        if stock is None or stock.current_price is None:
            return "no price: the stock has neither a realtime quote nor an official close"

        quantity = min(decision.quantity, held.quantity) if decision.action == TradeAction.SELL and held else decision.quantity
        follow = TradeSignal.of(
            stock,
            now,
            decision.action,
            SignalSource.FOLLOW,
            decision.score,
            f"Follows the {decision.action} of {decision.generated_at:%Y-%m-%d %H:%M}: {decision.reason}",
            quantity,
            decision.stop_loss_price,
        )
        return replace(follow, followed_decision_id=decision.decision_id)


@dataclass(
    frozen=True, kw_only=True, config=ConfigDict(json_schema_serialization_defaults_required=True, use_attribute_docstrings=True)
)
class RankingHoldings:
    """A mock account against the monthly ranking's latest decision. A ranking follow sells `left` and buys `lacking`."""

    decided_on: date | None = None
    """The decision session of the ranking. None before any ranking was read."""

    held: list[str] = Field(default_factory=list)
    """The ranking's stocks the account holds, best first."""

    lacking: list[str] = Field(default_factory=list)
    """The ranking's stocks the account does not hold, best first."""

    left: list[str] = Field(default_factory=list)
    """The stocks the account holds that the ranking does not, in stock id order."""

    @property
    def open(self) -> list[str]:
        """The stocks a follow trades, the sales first, so that what they free pays for the purchases."""
        return [*self.left, *self.lacking]


@dataclass(frozen=True)
class RankingHoldingsRule:
    """
    Which of the ranking's stocks the account holds and lacks, and which of its holdings the ranking left. A ranking of
    no stock, a month whose revenue the site does not hold, is no instruction to sell: it leaves all three empty.
    """

    def apply(self, ranking: Ranking, account: Account) -> RankingHoldings:
        ranked = [stock.stock_id for stock in ranking.stocks]

        if not ranked:
            return RankingHoldings(decided_on=ranking.decided_on)

        return RankingHoldings(
            decided_on=ranking.decided_on,
            held=[stock_id for stock_id in ranked if stock_id in account.stock_ids],
            lacking=[stock_id for stock_id in ranked if stock_id not in account.stock_ids],
            left=sorted(account.stock_ids.difference(ranked)),
        )


def sale_proceeds(
    sell: TradeSignal, now: datetime, limit_price_rule: LimitPriceRule, affordable_quantity_rule: AffordableQuantityRule
) -> float:
    limit_price = limit_price_rule.apply(TradeAction.SELL, sell.stock_id, sell.price_at_signal)

    return affordable_quantity_rule.cost_rule.apply(TradeAction.SELL, sell.stock_id, limit_price, sell.quantity, now=now).net


def buy_decision(rule: RankingFollowRule, stock: Stock, budget: float, reason: str, now: datetime) -> TradeSignal | str:
    limit_price = rule.limit_price_rule.apply(TradeAction.BUY, stock.stock_id, stock.current_price or 0.0)
    quantity = rule.affordable_quantity_rule.apply(
        cash=budget, stock_id=stock.stock_id, price=limit_price, lot_size=rule.lot_size, now=now
    )

    if quantity == 0:
        return f"{stock.stock_id}: its share of the account, {budget:,.0f}, buys no lot of {rule.lot_size} at {limit_price}"

    return TradeSignal.of(stock, now, TradeAction.BUY, SignalSource.RANKING, 0, reason, quantity)


@dataclass(frozen=True)
class RankingFollowRule:
    """
    The decisions that bring a mock account to the ranking at `now`, the sales first: a SELL of every share of each
    holding the ranking left, and a BUY of each ranked stock the account lacks. A ranked stock it holds already is left
    as it is, so a follow of a ranking it already holds decides nothing. Each BUY gets the same budget: the account's
    equity over the ranking's stocks, its equal weight, but no more than its share of the cash the account has once the
    sales settle, after their fee and tax. Its quantity is the most `lot_size` lots that budget pays for at the order's
    limit, fee included. A stock without a price, or whose budget buys no lot, gets a sentence saying so in place of a
    decision, and stays open to the next follow. The order gates judge each price when its order is placed.
    """

    lot_size: PositiveInt
    limit_price_rule: LimitPriceRule
    affordable_quantity_rule: AffordableQuantityRule

    def apply(self, ranking: Ranking, account: Account, stocks: Mapping[str, Stock], now: datetime) -> list[TradeSignal | str]:
        holdings = RankingHoldingsRule().apply(ranking, account)
        priced = {stock_id: stock for stock_id in holdings.open if (stock := stocks.get(stock_id)) and stock.current_price}
        unpriced = [
            f"{stock_id} has neither a realtime quote nor an official close" for stock_id in holdings.open if stock_id not in priced
        ]
        decision = f"the monthly ranking decided at the close of {ranking.decided_on}"
        sells = [
            TradeSignal.of(priced[stock_id], now, TradeAction.SELL, SignalSource.RANKING, 0, f"Left {decision}", position.quantity)
            for stock_id in holdings.left
            if stock_id in priced and (position := account.position_for(stock_id))
        ]
        entrants = [stock_id for stock_id in holdings.lacking if stock_id in priced]
        cash = account.cash + sum(sale_proceeds(sell, now, self.limit_price_rule, self.affordable_quantity_rule) for sell in sells)
        budget = min(account.equity / len(ranking.stocks), cash / len(entrants)) if entrants else 0.0
        places = {stock.stock_id: place for place, stock in enumerate(ranking.stocks, 1)}
        buys = [buy_decision(self, priced[stock_id], budget, f"Place {places[stock_id]} of {decision}", now) for stock_id in entrants]

        return [*unpriced, *sells, *buys]


@dataclass(
    frozen=True, kw_only=True, config=ConfigDict(json_schema_serialization_defaults_required=True, use_attribute_docstrings=True)
)
class FollowReturn:
    """What a mock account made since it first followed the ranking, against the benchmark over the same sessions."""

    since: date
    """The trading day of its first ranking follow that filled an order since the account opened."""

    until: date | None = None
    """The last session both returns count to. None until the history holds a session from `since` on."""

    account_return: float | None = None
    """
    The account's equity at the close of `until` over its equity at the close before `since`, less 1: its fees and tax
    are in it. The equity before is the cash the account opened with when it had filled no order by then.
    """

    benchmark_id: NonEmptyText
    benchmark_return: float | None = None
    """The benchmark's total return over the same sessions. None while the history holds no bar of it there."""


@dataclass(frozen=True)
class RankingFollowReturnRule:
    """
    The return of a mock account that first followed the ranking on `since`, from the close before that day to the last
    session of `history` the account's `curve` reaches, and the benchmark's total return over the same sessions, the
    benchmark the ranking's backtest holds. `curve` is the account at each trading day's close since its first fill.
    """

    benchmark_id: NonEmptyText

    def apply(self, since: date, opening: AccountOpening, curve: Mapping[date, Account], history: RankingHistory) -> FollowReturn:
        sessions, days = history.bars.sessions, sorted(curve)
        start, end = bisect_left(sessions, since) - 1, bisect_right(sessions, days[-1] if days else since) - 1
        measured = [day for day in days if since <= day <= sessions[end]] if end > start else []

        if not measured:
            return FollowReturn(since=since, benchmark_id=self.benchmark_id)

        before = [day for day in days if day < since]
        base = curve[before[-1]].equity if before else opening.initial_cash
        benchmark = None

        if start >= 0 and self.benchmark_id in history.bars.stock_ids:
            level = history.level[history.bars.stock_ids.index(self.benchmark_id)]
            benchmark = float(level[end] / level[start] - 1)

        return FollowReturn(
            since=since,
            until=sessions[end],
            account_return=curve[measured[-1]].equity / base - 1,
            benchmark_id=self.benchmark_id,
            benchmark_return=benchmark,
        )
