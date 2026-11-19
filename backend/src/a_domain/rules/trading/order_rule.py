import math
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated

from pydantic import Field
from pydantic.dataclasses import dataclass

from a_domain.model.system.user import User
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.collect.freshness import DataFreshnessRule
from a_domain.rules.trading.tick import LimitPriceRule
from a_domain.types.enums import (
    ExecutionProvider,
    FeatureVisibility,
    OrderPricing,
    OrderType,
    Permission,
    RejectReason,
    ShioajiServer,
    TimeInForce,
    TradeAction,
    TradingPhase,
    UserStatus,
    Workflow,
)
from a_domain.types.ids import RunId


@dataclass(frozen=True)
class OrderPriceRule:
    """
    Why the decision's price may not price an order at `now`, or None. A realtime quote counts while it is at most
    `price_freshness` old, measured to `now`, so a quote that was fresh when fetched but aged while the run analysed
    other stocks is refused. An official close counts only as the close of the last closed session (`last_close`, the
    time a daily bar of that session is stamped with): an older one is no longer the newest price, and a newer one
    does not exist yet.
    """

    pricing: OrderPricing
    price_freshness: DataFreshnessRule

    def apply(self, signal: TradeSignal, now: datetime, last_close: datetime) -> tuple[RejectReason, str] | None:
        match self.pricing:
            case OrderPricing.REALTIME_QUOTE:
                fresh = self.price_freshness.apply(signal.price_observed_at, now)
                limit = f"the limit is {int(self.price_freshness.max_lag.total_seconds() // 60)} min"
            case OrderPricing.OFFICIAL_CLOSE:
                fresh = signal.price_observed_at >= last_close
                limit = f"only the close of {last_close:%Y-%m-%d} prices an order now"

        if fresh:
            return None

        age_minutes = int((now - signal.price_observed_at).total_seconds() // 60)
        detail = (
            f"price {signal.price_at_signal:.2f} was quoted at {signal.price_observed_at:%Y-%m-%d %H:%M}, "
            f"{age_minutes} min before {now:%H:%M}; {limit}"
        )
        return RejectReason.STALE_PRICE, detail


@dataclass(frozen=True)
class OrderGateRule:
    """
    Why the app may not send an order for this decision now, or None, whichever broker takes it. The gates run per
    decision right before submission, against one reading of the clock: the trading phase the order pricing allows (a
    realtime quote prices an order in continuous trading only, since the opening and closing call auctions take ROD
    only and the app sends IOC; an official close prices a mock order only while no session trades), and the price's
    age (OrderPriceRule). Which broker may take the order is BrokerAccessRule's, checked at the send itself.
    """

    price_rule: OrderPriceRule

    def apply(self, signal: TradeSignal, now: datetime, phase: TradingPhase, last_close: datetime) -> tuple[RejectReason, str] | None:
        pricing = self.price_rule.pricing

        if phase != pricing.trading_phase:
            detail = (
                f"{now:%a %Y-%m-%d %H:%M} falls in the market's {phase} phase; {pricing} orders go in its {pricing.trading_phase} only"
            )
            return pricing.outside_phase, detail

        return self.price_rule.apply(signal, now, last_close)


@dataclass(frozen=True, kw_only=True)
class BrokerLink:
    """
    What an order sent now would reach, as the broker reports it right before the send: which broker, whether its
    login is up, and whether that login is on the broker's simulation server. The mock account has no login: it is
    always up, on no server.
    """

    broker: ExecutionProvider
    up: bool = True
    simulation: bool | None = None

    @property
    def on_simulation_server(self) -> bool:
        """
        The login that answered is on the broker's simulation server, which holds no real money. False for a login on
        the production server, and for the mock account, which has no login.
        """
        return self.simulation is True


@dataclass(frozen=True, kw_only=True)
class SiteOrdering:
    """
    What the site's ordering switch says at one ask, from one read of the settings files on disk (IOrderingSwitch):
    whom the site lets order on each broker (`ordering`, each broker's ordering feature, features.*) and the SinoPac
    server shioaji.server names (`server`).
    """

    ordering: dict[ExecutionProvider, FeatureVisibility]
    server: ShioajiServer


@dataclass(frozen=True)
class BuyLimitRule:
    """
    Why a BUY on a real broker may not be sent, or None: its value, the limit price times the shares, above
    max_order_value, or with the day's earlier BUYs on that broker above max_daily_buy_value. An earlier BUY counts at
    what it may have bought: all of it while its outcome is open or unknown (PENDING, SUBMITTED, UNCONFIRMED, FAILED), what filled
    once it ended, and nothing when refused. The journal holds each order before it is sent, so the earlier BUYs are
    every one that may have reached the broker. A BUY with no limit price, a MARKET order, has no value to hold to them,
    so it is refused. A SELL is never held to them: it sells only shares the account holds.
    """

    max_order_value: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    max_daily_buy_value: Annotated[float, Field(gt=0, allow_inf_nan=False)]

    def apply(self, order: Order, earlier_buys: Sequence[Order]) -> tuple[RejectReason, str] | None:
        if order.action != TradeAction.BUY:
            return None

        if order.limit_price is None:
            limits = "trading.max_order_value and trading.max_daily_buy_value"
            return RejectReason.ORDER_VALUE_LIMIT, f"has no limit price to value against {limits}"

        value = order.limit_price * order.quantity

        if value > self.max_order_value:
            return (
                RejectReason.ORDER_VALUE_LIMIT,
                f"costs {value:,.0f} at its limit, above trading.max_order_value {self.max_order_value:,.0f}",
            )

        bought = math.fsum(
            (earlier.limit_price or 0) * (earlier.filled_quantity if earlier.status.fill_final else earlier.quantity)
            for earlier in earlier_buys
            if earlier.id != order.id
        )

        if bought + value > self.max_daily_buy_value:
            limit = f"trading.max_daily_buy_value {self.max_daily_buy_value:,.0f}"
            return RejectReason.DAILY_BUY_LIMIT, f"costs {value:,.0f} after {bought:,.0f} of BUYs today, above {limit}"

        return None


@dataclass(frozen=True)
class UnsettledBuyRule:
    """
    Why a BUY on a real broker may not be sent while an earlier BUY of the same stock on it today is still open, or
    None: one that awaits settlement (UNCONFIRMED), one a process that stopped left PENDING or SUBMITTED, before the
    Web API's timer ended its run (AbandonedRuns) or in a CLI session, and one another run sends at this moment. The
    broker may still deal that one, so a second could buy the stock twice. Once it ended, or the broker's record of the
    day settled it (OrderSettlement, which a run on the broker runs before it sends anything), the BUY may go. A SELL
    is never held to it: it sells only shares the account holds. `earlier_buys` may hold `order` itself, which never
    holds itself back.
    """

    def apply(self, order: Order, earlier_buys: Sequence[Order]) -> tuple[RejectReason, str] | None:
        if order.action != TradeAction.BUY:
            return None

        held_back = [
            earlier
            for earlier in earlier_buys
            if earlier.stock_id == order.stock_id and earlier.status.is_open and earlier.id != order.id
        ]

        if not held_back:
            return None

        return (
            RejectReason.UNSETTLED_BUY,
            f"order {held_back[0].id}, an earlier BUY of {order.stock_id} today, is {held_back[0].status.value} and may "
            f"still deal: another BUY of {order.stock_id} waits until it ends or the broker's record of the day settles it",
        )


@dataclass(frozen=True)
class RealBrokerOrdererRule:
    """
    Why `user` may not order on the real `broker`, or None. The site's own switch comes first: `ordering` is whom the
    site lets order on the broker now, the visibility of the broker's ordering feature (features.*) as the site holds
    it at this send, not as the run's settings held it at its start, and an order of anyone else is refused, of
    everyone while it is off, whatever the environment and the user's role. Then the user, as saved now, must be active
    with USE_REAL_BROKER.
    """

    def apply(self, broker: ExecutionProvider, user: User | None, ordering: FeatureVisibility) -> tuple[RejectReason, str] | None:
        if not ordering.shown_to(user.permissions if user is not None else frozenset()):
            return RejectReason.ORDERING_OFF, f"this site has ordering on {broker.value} off: features.{broker.ordering_feature.value}"

        if user is None or user.status != UserStatus.ACTIVE or Permission.USE_REAL_BROKER not in user.permissions:
            return RejectReason.REAL_BROKER_REFUSED, f"only an active administrator orders on {broker.value}"

        return None


@dataclass(frozen=True)
class BrokerLoginRule:
    """
    Why a real broker's login may not take an order now, or None: it must be up, and on the server the settings files
    on disk name at this ask (`server`, SiteOrdering.server), not the server of the settings the run started on.
    """

    def apply(self, link: BrokerLink, server: ShioajiServer) -> tuple[RejectReason, str] | None:
        if not link.up:
            return RejectReason.BROKER_LOGIN_DOWN, f"the {link.broker.value} login is down"

        if link.simulation != server.simulation:
            return (
                RejectReason.BROKER_SERVER_MISMATCH,
                f"the {link.broker.value} login is not on the {server.value} server shioaji.server names on disk now",
            )

        return None


@dataclass(frozen=True)
class SimulationOnlyRule:
    """
    Why an order of a run of `workflow` may not go to what `link` reaches, or None. A workflow that orders on a real
    broker's simulation server only (Workflow.simulation_only: a ranking follow) is refused on a real broker unless the
    login that answers is on that server (BrokerLink.on_simulation_server), whatever the environment, the settings and
    the user: it never orders with real money. The server it reads is the flag the broker's SDK client was constructed
    with, which the client that sends the order reports of itself (BrokerLink.simulation). This app sets that flag from
    shioaji.server when it logs in, and this rule reads that setting nowhere, so it refuses a client made for the
    production server whatever the settings say. No setting lifts it.
    """

    def apply(self, workflow: Workflow, link: BrokerLink) -> tuple[RejectReason, str] | None:
        if not link.broker.real or not workflow.simulation_only or link.on_simulation_server:
            return None

        return (
            RejectReason.NOT_SIMULATION,
            f"a {workflow.value} orders on {link.broker.value}'s simulation server only, and this login is not on it",
        )


@dataclass(frozen=True)
class RealBrokerGateRule:
    """
    Why a run of `workflow` by `user` may not order on `broker` now, or None: the one gate of a real broker
    (ExecutionProvider.real), asked before a ranking follow starts, for the accounts My settings offers, by the
    schedule's timer, and of every order right before its send (BrokerAccessRule). The mock account passes, whatever
    `ordering`. A real broker passes only while the site holds a login on it (`link`, what that login reports of itself
    now; None where the site holds none), and three rules then decide, in this order: whether the workflow may order on
    the login's server (SimulationOnlyRule), who may order on the broker at all (RealBrokerOrdererRule: the site's
    ordering switch as one read found it, `ordering`, then the user as saved now), and the login, up and on the server
    the same read names (BrokerLoginRule). Settings files on disk that do not load (`ordering` None) let nobody order.
    """

    simulation_rule: SimulationOnlyRule
    orderer_rule: RealBrokerOrdererRule
    login_rule: BrokerLoginRule

    def apply(
        self, workflow: Workflow, broker: ExecutionProvider, link: BrokerLink | None, user: User | None, ordering: SiteOrdering | None
    ) -> tuple[RejectReason, str] | None:
        if not broker.real:
            return None

        if link is None or link.broker != broker:
            return RejectReason.BROKER_LOGIN_DOWN, f"this site holds no {broker.value} login"

        if refused := self.simulation_rule.apply(workflow, link):
            return refused

        if ordering is None:
            return RejectReason.ORDERING_OFF, "the settings files on disk do not load, so this site lets nobody order"

        return self.orderer_rule.apply(broker, user, ordering.ordering[broker]) or self.login_rule.apply(link, ordering.server)


@dataclass(frozen=True)
class BrokerAccessRule:
    """
    Why an order may not go to the broker it would reach now, or None, checked right before the send: it must be the
    broker its run chose when it started, and one the site's audience and order pricing offer (`brokers`). A real
    broker must then pass its gate (RealBrokerGateRule: the workflow on the login's server, who may order, the login
    on the server the settings on disk name), and a BUY no earlier BUY of its stock still open (UnsettledBuyRule)
    and its limits (BuyLimitRule).
    """

    brokers: frozenset[ExecutionProvider]
    gate_rule: RealBrokerGateRule
    unsettled_rule: UnsettledBuyRule
    limit_rule: BuyLimitRule

    def apply(
        self,
        order: Order,
        workflow: Workflow,
        run_broker: ExecutionProvider,
        link: BrokerLink,
        user: User | None,
        ordering: SiteOrdering | None,
        earlier_buys: Sequence[Order],
    ) -> tuple[RejectReason, str] | None:
        broker = link.broker

        if broker != run_broker:
            return RejectReason.BROKER_NOT_CHOSEN, f"the run chose {run_broker.value}, and this order would reach {broker.value}"

        if broker not in self.brokers:
            return RejectReason.BROKER_NOT_OFFERED, f"this site orders on {', '.join(sorted(self.brokers))} only, not {broker.value}"

        if not broker.real:
            return None

        return (
            self.gate_rule.apply(workflow, broker, link, user, ordering)
            or self.unsettled_rule.apply(order, earlier_buys)
            or self.limit_rule.apply(order, earlier_buys)
        )


@dataclass(frozen=True)
class OrderRule:
    """
    Turns a BUY or SELL decision into the order the app may send now, or into a REJECTED order that says why not
    (OrderGateRule).

    Every order is a LIMIT at the decision's price with time in force IOC:
    - LIMIT at the price the decision saw, as an exchange tick (LimitPriceRule). A traded price is a tick, so no fill
      is worse than what was decided on. A price off the tick grid rounds up for a BUY and down for a SELL, at most
      one tick, so the order still executes at that price.
    - IOC trades what is available at that price now and cancels the rest at once. The app tracks no
      working orders (no cancel, no expiry, no reconciliation), so ROD is out: its remainder could fill
      hours later at a price no decision saw. FOK is out because sizing gives a maximum, not a target:
      a partial BUY is still a valid smaller position and a partial stop-loss SELL still cuts the loss.
    - IOC trades only in continuous trading, so an order outside it is REJECTED as MARKET_CLOSED and never sent.
    """

    gate_rule: OrderGateRule
    limit_price_rule: LimitPriceRule

    def apply(self, signal: TradeSignal, run_id: RunId, now: datetime, phase: TradingPhase, last_close: datetime) -> Order:
        action = signal.action

        if action == TradeAction.HOLD:
            raise ValueError("HOLD is not an order")

        order = Order(
            run_id=run_id,
            decision_id=signal.decision_id,
            stock_id=signal.stock_id,
            action=action,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.IOC,
            quantity=signal.quantity,
            limit_price=self.limit_price_rule.apply(action, signal.stock_id, signal.price_at_signal),
            created_at=now,
            updated_at=now,
        )
        refusal = self.gate_rule.apply(signal, now, phase, last_close)

        if refusal is not None:
            order.reject(*refusal, now=now)

        return order
