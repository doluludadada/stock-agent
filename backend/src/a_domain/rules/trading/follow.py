import math
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence, Sized
from dataclasses import replace
from datetime import date, datetime, time, timedelta

from pydantic import ConfigDict, Field, PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.system.user import User
from a_domain.model.trading.account import Account, AccountOpening, Position
from a_domain.model.trading.order import Order
from a_domain.model.trading.ranking_formula import RankingFormula
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.cost import AffordableQuantityRule
from a_domain.rules.trading.order_rule import (
    BrokerLink,
    BuyLimitRule,
    RealBrokerGateRule,
    SiteOrdering,
    daily_buy_limit,
    may_have_bought,
    order_value_limit,
)
from a_domain.rules.trading.ranking import DecisionSessionsRule, Ranking, RankingHistory
from a_domain.rules.trading.tick import LimitPriceRule
from a_domain.types.enums import (
    ExecutionProvider,
    FeatureVisibility,
    FollowAccountRefusal,
    FollowRefusal,
    OrderPricing,
    ShioajiServer,
    SignalSource,
    TradeAction,
    TradingPhase,
    Workflow,
)
from a_domain.types.values import Fraction, NonEmptyText


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
    """An account against the monthly ranking's latest decision. A ranking follow sells `left` and buys `lacking`."""

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
    Which of the ranking's stocks an account that holds `held`, the ids of its positions, holds and lacks, and which of
    its holdings the ranking left. A ranking whose formula holds cash left every holding. Any other ranking of no
    stock, a month whose revenue the site does not hold, is no instruction to sell: it leaves all three empty.
    """

    def apply(self, ranking: Ranking, held: frozenset[str]) -> RankingHoldings:
        ranked = [stock.stock_id for stock in ranking.stocks]

        if not ranking.decides:
            return RankingHoldings(decided_on=ranking.decided_on)

        return RankingHoldings(
            decided_on=ranking.decided_on,
            held=[stock_id for stock_id in ranked if stock_id in held],
            lacking=[stock_id for stock_id in ranked if stock_id not in held],
            left=sorted(held.difference(ranked)),
        )


@dataclass(frozen=True, kw_only=True, config=ConfigDict(use_attribute_docstrings=True))
class FollowAccount:
    """
    The user's follow account (User.ranking_follow_broker), whether a ranking follow may order there now, and the
    accounts the site offers them as one.
    """

    broker: ExecutionProvider
    """The user's follow account."""

    brokers: tuple[ExecutionProvider, ...]
    """The accounts the site offers the user as their follow account now, the mock account first."""

    refusal: FollowAccountRefusal | None
    """Why the site does not offer the user `broker` now, so no follow orders there; None while it is one of `brokers`."""

    server: ShioajiServer | None
    """The server of the site's login on the real broker, as the login reports itself. None where the user's Pipeline holds none."""

    @property
    def measured(self) -> bool:
        """The site measures the follow's return on the account: it keeps the account's history and offers it to the user now."""
        return self.refusal is None and self.broker.equity_history


@dataclass(frozen=True)
class FollowAccountRule:
    """
    The user's follow account and the accounts the site offers them as one now. The site offers an account only while
    it shows the user that account (`accounts`, the visibility of each broker's account feature) and ordering on it
    (`ordering`, one read of the site's ordering switch), and a real broker only while its gate lets a ranking follow
    order there (RealBrokerGateRule), with who may order asked before the login: a user the site would never let order
    there is told so whatever the login. `links` are what the real brokers' logins the user's Pipeline holds report of
    themselves now.
    """

    gate_rule: RealBrokerGateRule
    accounts: Mapping[ExecutionProvider, FeatureVisibility]

    def apply(self, user: User, links: Mapping[ExecutionProvider, BrokerLink], ordering: SiteOrdering | None) -> FollowAccount:
        refusals = {broker: account_refusal(self, broker, user, links.get(broker), ordering) for broker in ExecutionProvider}
        servers = [ShioajiServer.of_client(link.simulation) for link in links.values() if link.simulation is not None]

        return FollowAccount(
            broker=user.ranking_follow_broker,
            brokers=tuple(broker for broker, refusal in refusals.items() if refusal is None),
            refusal=refusals[user.ranking_follow_broker],
            server=servers[0] if servers else None,
        )


def account_refusal(
    rule: FollowAccountRule, broker: ExecutionProvider, user: User, link: BrokerLink | None, ordering: SiteOrdering | None
) -> FollowAccountRefusal | None:
    """
    Why the site does not offer `user` the account on `broker` as their follow account now, or None. Settings files on
    disk that do not load (`ordering` None) show nobody ordering on any account.
    """
    visibility = ordering.ordering[broker] if ordering is not None else FeatureVisibility.OFF

    if not (rule.accounts[broker].shown_to(user.permissions) and visibility.shown_to(user.permissions)):
        return FollowAccountRefusal.ORDERING_OFF

    if broker.real and (refused := rule.gate_rule.orderer_rule.apply(broker, user, visibility)) is not None:
        return refused[0].follow_refusal

    if (refused := rule.gate_rule.apply(Workflow.RANKING_FOLLOW, broker, link, user, ordering)) is not None:
        return refused[0].follow_refusal

    return None


@dataclass(frozen=True, kw_only=True, config=ConfigDict(use_attribute_docstrings=True))
class FollowSchedule:
    """A user's schedule of the ranking follow on their follow account, and where it stands now."""

    time: time | None
    """The time of day in Taipei from which the site follows by itself. None: the schedule is off."""

    times: tuple[time, ...]
    """The times the site offers."""

    pending: date | None
    """
    The ranking's latest decision while a session after it has come and no ranking follow of the account finished it
    under the active formula, by the schedule or by hand. The schedule follows it on each session it can, once a day,
    until a follow leaves nothing to trade. None once one did, and while the history holds no decision.
    """

    unfinished: SystemStats | None
    """
    The schedule's last follow of `pending` that left it pending, with why in its record: a `failure`, no
    `ranking_open` when it could not start, or the stocks it left to trade. None while the schedule has not tried.
    """

    due: bool
    """
    The schedule follows `pending` now: it is on, the site offers the user their follow account, its time has come
    today, and the market is in the phase orders are placed in.
    """


@dataclass(frozen=True)
class FollowTimeRule:
    """
    Whether a schedule of `follow_time` may follow at `now`, the market's own time: the schedule is on, the time has
    come today, and the market is in the one phase this site places an order in, so a day whose window was missed is
    left to the next session.
    """

    pricing: OrderPricing

    def apply(self, follow_time: time | None, now: datetime, phase: TradingPhase) -> bool:
        return follow_time is not None and phase == self.pricing.trading_phase and now.time() >= follow_time


def scheduled_since(follows: Sequence[SystemStats], day: date, now: datetime) -> list[SystemStats]:
    """The follows the schedule started from `day` on, in the market's own days, as given: oldest first."""
    return [follow for follow in follows if follow.scheduled and follow.start_time.astimezone(now.tzinfo).date() >= day]


def left_nothing_to_trade(follow: SystemStats) -> bool:
    """Whether a ranking follow left the account nothing to trade for the decision it took: the account holds that ranking."""
    return follow.ranking_open == 0


def unfinished_follow(follows: Sequence[SystemStats], pending: date | None, now: datetime) -> SystemStats | None:
    """The schedule's last follow since the day after the `pending` decision that did not leave the account nothing to trade."""
    if pending is None:
        return None

    tries = [follow for follow in scheduled_since(follows, pending + timedelta(days=1), now) if not left_nothing_to_trade(follow)]

    return tries[-1] if tries else None


@dataclass(frozen=True)
class FollowScheduleRule:
    """
    Where a user's schedule of the ranking follow stands at `now`. The decision to follow is the ranking's latest one
    among `sessions` (DecisionSessionsRule) once a day after it has come: an older one is superseded and never
    followed late. Whether the decision is finished is judged on the follows on the user's follow account (`account`),
    so a follow that finished it in another account finishes nothing here; a follow the schedule started today counts
    on whatever account, so a user who changes their follow account is still followed once a day. The decision is
    pending until one ranking follow of the account finished it under `formula`, the active one: it took that decision
    by that formula as it is defined now and left nothing to trade, whoever started it. So the schedule never repeats
    a finished follow or one the user finished by hand, it goes on after a follow that ordered nothing or only a part,
    and it brings the account to a formula an administrator switched to. It is due when the site offers the user their
    follow account now, the schedule may follow now (FollowTimeRule) and has started no follow yet today: a scheduled
    follow that failed, was refused or left stocks to trade is tried again on the next session, not every minute of
    this one.
    """

    decision_rule: DecisionSessionsRule
    time_rule: FollowTimeRule
    times: tuple[time, ...]
    formula: RankingFormula

    def apply(
        self,
        follow_time: time | None,
        sessions: Sequence[date],
        follows: Sequence[SystemStats],
        now: datetime,
        phase: TradingPhase,
        account: FollowAccount,
    ) -> FollowSchedule:
        tried_today = bool(scheduled_since(follows, now.date(), now))
        follows = [follow for follow in follows if follow.execution_provider == account.broker]
        decisions = self.decision_rule.apply(sessions)
        decided_on = sessions[decisions[-1][0]] if decisions else None
        finished = any(
            left_nothing_to_trade(follow) and follow.ranking_decided_on == decided_on and follow.ranking_formula == self.formula
            for follow in follows
        )
        pending = decided_on if decided_on is not None and decided_on < now.date() and not finished else None

        return FollowSchedule(
            time=follow_time,
            times=self.times,
            pending=pending,
            unfinished=unfinished_follow(follows, pending, now),
            due=pending is not None and account.refusal is None and not tried_today and self.time_rule.apply(follow_time, now, phase),
        )


def sale_proceeds(
    sell: TradeSignal, now: datetime, limit_price_rule: LimitPriceRule, affordable_quantity_rule: AffordableQuantityRule
) -> float:
    """What `sell` brings after its fee and tax at its limit, the least it fills at: up to trading.limit_offset_pct under its price."""
    limit_price = limit_price_rule.apply(TradeAction.SELL, sell.stock_id, sell.price_at_signal)

    return affordable_quantity_rule.cost_rule.apply(TradeAction.SELL, sell.stock_id, limit_price, sell.quantity, now=now).net


def ranking_decision(ranking: Ranking) -> str:
    """The decision a follow takes, as each of its decisions' reasons names it."""
    return f"the monthly ranking {ranking.formula.name} decided at the close of {ranking.decided_on}"


def ranking_sales(
    ranking: Ranking, account: Account, left: Sequence[str], priced: Mapping[str, Stock], now: datetime
) -> list[TradeSignal]:
    """A SELL of every share of each holding of `left`, which the ranking left, at its price in `priced`."""
    return [
        TradeSignal.of(
            priced[stock_id], now, TradeAction.SELL, SignalSource.RANKING, 0, f"Left {ranking_decision(ranking)}", position.quantity
        )
        for stock_id in left
        if (position := account.position_for(stock_id))
    ]


def buy_reason(ranking: Ranking, stock_id: str, switched: RankingFormula | None) -> str:
    """A follow's BUY of `stock_id`: its place in the ranking, and for a top-up the formula switched from (switched_from)."""
    place = next(place for place, stock in enumerate(ranking.stocks, 1) if stock.stock_id == stock_id)
    reason = f"Place {place} of {ranking_decision(ranking)}"

    return f"{reason}, up to its equal weight since the switch from {switched.name}" if switched is not None else reason


def buy_decision(rule: RankingFollowRule, stock: Stock, budget: float, reason: str, now: datetime) -> TradeSignal | str:
    limit_price = rule.limit_price_rule.apply(TradeAction.BUY, stock.stock_id, stock.current_price or 0.0)
    quantity = rule.affordable_quantity_rule.apply(
        cash=budget, stock_id=stock.stock_id, price=limit_price, lot_size=rule.lot_size, now=now
    )

    if quantity == 0:
        return f"{stock.stock_id}: its share of the account, {budget:,.0f}, buys no lot of {rule.lot_size} at {limit_price}"

    return TradeSignal.of(stock, now, TradeAction.BUY, SignalSource.RANKING, 0, reason, quantity)


def switched_from(follows: Sequence[SystemStats], formula: RankingFormula) -> RankingFormula | None:
    """
    The formula of the account's last finished ranking follow, of `follows` oldest first the last that left it nothing
    to trade, while it is another than `formula`: the active formula was switched since, and no follow under it
    finished. None before the account finished any follow, and once one under `formula` did.
    """
    finished = [follow.ranking_formula for follow in follows if left_nothing_to_trade(follow) and follow.ranking_formula is not None]

    return finished[-1] if finished and finished[-1] != formula else None


def short_of_weight(position: Position, stock: Stock | None, weight: float, tolerance: float) -> bool:
    """
    Whether `position`, at the run's price of `stock`, is worth less than `weight` by more than `tolerance` of it, or may
    be: a stock without a price.
    """
    if stock is None or stock.current_price is None:
        return True

    return weight - position.quantity * stock.current_price > tolerance * weight


@dataclass(frozen=True)
class TopUpRule:
    """
    The ranked stocks an account holds that a ranking follow tops up to their equal weight, best first. None but on a
    follow after a switch of the active formula: while the account's last finished ranking follow, the last of
    `follows` (oldest first) that left it nothing to trade, used another formula than the ranking's (switched_from).
    There, each ranked stock it holds of `positions` whose position, at its price in `priced`, is worth less than its
    equal weight, `equity` over the ranking's stocks, by more than `tolerance` of that weight, and each without a price,
    which may be. Before the run valued the account (`equity` None) every ranked stock it holds may be one, so a switch
    follow of an account that holds the ranking alone has something to follow.

    A follow that tops up counts each it did not buy as left to trade, so the schedule tries the decision again on the
    next session, still a switch follow, with the cash that settled since: on SinoPac, which pays a sale at settlement,
    the first follow after a switch may top up nothing. The tolerance keeps the mock account from buying a few shares
    every session: a BUY sized at its limit, up to trading.limit_offset_pct above the price it fills at, leaves about
    that share of the weight unbought, and each BUY pays a minimum fee.
    """

    tolerance: Fraction

    def apply(
        self,
        ranking: Ranking,
        positions: Sequence[Position],
        follows: Sequence[SystemStats],
        priced: Mapping[str, Stock],
        equity: float | None,
    ) -> list[str]:
        held = {position.stock_id: position for position in positions}
        ranked = [stock.stock_id for stock in ranking.stocks if stock.stock_id in held]

        if not ranked or switched_from(follows, ranking.formula) is None:
            return []

        if equity is None:
            return ranked

        weight = equity / len(ranking.stocks)
        return [stock_id for stock_id in ranked if short_of_weight(held[stock_id], priced.get(stock_id), weight, self.tolerance)]


def buy_wants(account: Account, ranking: Ranking, buying: Sequence[str]) -> dict[str, float]:
    """
    What each BUY of `buying`, priced stocks of the ranking, wants to cost, best first: its equal weight, the account's
    equity over the ranking's stocks, less what the account's position of it is worth at the run's price. A stock it
    lacks wants the whole weight; one it holds at its weight or more wants nothing and is left out.
    """
    weight = account.equity / len(ranking.stocks) if ranking.stocks else 0.0
    held = {position.stock_id: position.market_value for position in account.positions}
    wants = {stock.stock_id: weight - held.get(stock.stock_id, 0.0) for stock in ranking.stocks if stock.stock_id in buying}

    return {stock_id: want for stock_id, want in wants.items() if want > 0 or stock_id not in held}


def buy_budgets(
    rule: RankingFollowRule, account: Account, broker: ExecutionProvider, wants: Mapping[str, float], cash: float
) -> dict[str, float]:
    """
    What each BUY of a follow may cost, by stock: what it wants (buy_wants). On a broker that credits a sale at its fill
    every BUY is cut by the same share until together they want no more than `cash`, the account's cash with this
    follow's sales in it, so every BUY is made smaller alike; on a real broker none costs more than one BUY may cost
    there (order_value_limit).
    """
    wanted = sum(wants.values())
    share = min(1.0, cash / wanted) if broker.credits_sales_at_once and wanted > 0 else 1.0
    most = order_value_limit(rule.buy_limit_rule, account.equity) if broker.real else math.inf

    return {stock_id: min(want * share, most) for stock_id, want in wants.items()}


def buying_bounds(
    rule: RankingFollowRule,
    account: Account,
    broker: ExecutionProvider,
    earlier_buys: Sequence[Order],
    trading_available: float | None,
) -> dict[str, float]:
    """
    What a follow's BUYs together may cost on `broker` now, each bound named by what sets it. A broker that pays a sale
    at settlement (ExecutionProvider.credits_sales_at_once) accepts a BUY on the cash the account has now alone. A real
    broker holds the day's BUYs to the day's BUY limit (BuyLimitRule), so the BUYs take no more than what its earlier
    BUYs of the day left of it; and it may hold the account to its own trading limit, which the follow then stays in
    where the broker says one (`trading_available`). The mock account credits a sale at its fill and has no BUY limit:
    it bounds nothing here.
    """
    bounds = {} if broker.credits_sales_at_once else {"the account's cash (a sale's proceeds count once they settle)": account.cash}

    if not broker.real:
        return bounds

    room = daily_buy_limit(rule.buy_limit_rule, account.equity) - may_have_bought(earlier_buys)
    bounds["the day's BUY limit (trading.max_daily_buy_equity_pct)"] = room

    if trading_available is not None:
        bounds[f"{broker.label}'s own trading limit"] = trading_available

    return bounds


def buys_paid_for(
    rule: RankingFollowRule, buys: Sequence[TradeSignal | str], bounds: Mapping[str, float], now: datetime
) -> list[TradeSignal | str]:
    """
    `buys` as given, best first, each BUY kept whole while every bound of `bounds` still pays for it at its limit, fee
    included, after the BUYs kept before it. A BUY one bound does not pay for becomes a sentence naming that bound: it
    is not made smaller, so a later follow buys it at its full share, and the BUYs after it are tried.
    """
    left = dict(bounds)
    paid: list[TradeSignal | str] = []

    for buy in buys:
        if isinstance(buy, str):
            paid.append(buy)
            continue

        limit_price = rule.limit_price_rule.apply(TradeAction.BUY, buy.stock_id, buy.price_at_signal)
        cost = -rule.affordable_quantity_rule.cost_rule.apply(TradeAction.BUY, buy.stock_id, limit_price, buy.quantity, now=now).net
        short = next((bound for bound, amount in left.items() if cost > amount), None)

        if short is not None:
            paid.append(
                f"{buy.stock_id}: a BUY of {buy.quantity} costs {cost:,.0f}, and {short} leaves {left[short]:,.0f} to buy with now"
            )
            continue

        paid.append(buy)
        left = {bound: amount - cost for bound, amount in left.items()}

    return paid


@dataclass(frozen=True)
class RankingFollowRule:
    """
    The decisions that bring an account on `broker` to the ranking at `now`, the sales first: a SELL of every share of
    each holding the ranking left, and a BUY of each ranked stock the account lacks. A ranked stock it holds already is
    left as it is, so a follow of a ranking it already holds decides nothing, and no purchase is split over sessions.
    One follow differs: while the account's last finished follow, the last of `follows` (its ranking follows, oldest
    first) that left it nothing to trade, used another formula than the ranking's (switched_from), the follow also tops
    up each ranked stock the account holds that falls short of its equal weight by more than
    ranking.top_up_tolerance_pct of it (TopUpRule), with a BUY of what its position lacks of the weight at the run's
    price, inside the same bounds and best first. A switch from 20 stocks to 10 would otherwise sell ten and buy
    nothing, half the account in cash until stocks rotate. A top-up the follow does not buy is left to trade, so the
    follow does not finish the decision and the next one is a switch follow again; once a follow under the new formula
    finished, no later one tops up.

    Each BUY's budget is what it wants (buy_wants): the account's equity, as the run valued it, over the ranking's
    stocks, its equal weight, less what the account holds of the stock, and on a real broker no more than the most one
    BUY may cost there (order_value_limit), so a BUY is sized inside that limit and never refused for its own size. Its
    quantity is the most `lot_size` lots that budget pays for at the order's limit, fee included, so it stays affordable
    whatever the market fills it at. The mock account fills at the decided price, so there about trading.limit_offset_pct
    (2%) of what a follow bought, and as much of what it sold, stays as cash: its BUYs are sized at their limits above
    the decided prices and its sales counted at their limits below them (sale_proceeds).

    The BUYs together cost no more than what the account may buy with now, and how they fit it depends on when the
    broker credits a sale (ExecutionProvider.credits_sales_at_once). The mock account credits a sale at its fill, so
    there the cash holds what this follow's sales bring after their fee and tax, and every BUY is made smaller alike
    until all fit (buy_budgets). Elsewhere no BUY is made smaller: the BUYs are kept best first while every bound of
    buying_bounds pays for them whole (the cash the account has now, without this follow's sales, and on a real broker
    what the day's BUY limit leaves after the day's earlier BUYs, `earlier_buys`, and the broker's own trading limit
    where it says one, `trading_available`), and the rest wait for a later follow. A smaller BUY would leave the account
    holding the stock, and no later follow but the first after a switch would add to it.

    A stock without a price, whose budget buys no lot, or that a bound does not pay for now gets a sentence saying so
    in place of a decision, and stays open to the next follow, a top-up too: on SinoPac, which pays a sale at
    settlement, the first follow after a switch tops up with the cash the account has before its sales settle, and the
    next session's follow with the cash that settled since. The order gates judge each price when its order is placed,
    and on a real broker the BUY limits again, against BUYs another run sent since.
    """

    lot_size: PositiveInt
    buy_limit_rule: BuyLimitRule
    limit_price_rule: LimitPriceRule
    affordable_quantity_rule: AffordableQuantityRule
    top_up_rule: TopUpRule

    def apply(
        self,
        ranking: Ranking,
        account: Account,
        stocks: Mapping[str, Stock],
        now: datetime,
        broker: ExecutionProvider,
        earlier_buys: Sequence[Order],
        trading_available: float | None,
        follows: Sequence[SystemStats],
    ) -> list[TradeSignal | str]:
        holdings = RankingHoldingsRule().apply(ranking, account.stock_ids)
        former = switched_from(follows, ranking.formula)
        topped_up = self.top_up_rule.apply(ranking, account.positions, follows, stocks, account.equity)
        traded = [*holdings.open, *topped_up]
        priced = {stock_id: stock for stock_id in traded if (stock := stocks.get(stock_id)) and stock.current_price}
        unpriced = [f"{stock_id} has neither a realtime quote nor an official close" for stock_id in traded if stock_id not in priced]
        sells = ranking_sales(ranking, account, [stock_id for stock_id in holdings.left if stock_id in priced], priced, now)
        wants = buy_wants(account, ranking, [stock_id for stock_id in [*holdings.lacking, *topped_up] if stock_id in priced])
        cash = account.cash + sum(sale_proceeds(sell, now, self.limit_price_rule, self.affordable_quantity_rule) for sell in sells)
        buys = [
            buy_decision(self, priced[stock_id], budget, buy_reason(ranking, stock_id, former if stock_id in topped_up else None), now)
            for stock_id, budget in buy_budgets(self, account, broker, wants, cash).items()
        ]
        bounds = buying_bounds(self, account, broker, earlier_buys, trading_available)

        return [*unpriced, *sells, *buys_paid_for(self, buys, bounds, now)]


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
