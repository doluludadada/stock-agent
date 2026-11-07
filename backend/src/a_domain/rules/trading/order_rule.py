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
    OrderPricing,
    OrderType,
    Permission,
    RejectReason,
    TimeInForce,
    TradeAction,
    TradingPhase,
    UserStatus,
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


@dataclass(frozen=True)
class BuyLimitRule:
    """
    Why a BUY on a real broker may not be sent, or None: its value, the limit price times the shares, above
    max_order_value, or with the day's earlier BUYs on that broker above max_daily_buy_value. An earlier BUY counts at
    what it may have bought: all of it while its outcome is open or unknown (PENDING, SUBMITTED, FAILED), what filled
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
class BrokerAccessRule:
    """
    Why an order may not go to the broker it would reach now, or None, checked right before the send: it must be the
    broker its run chose when it started, one the site's audience and order pricing offer (`brokers`), and for a real
    broker (ExecutionProvider.real) the user, as saved now, must be active with USE_REAL_BROKER, the broker's login must
    be up, and on the server the environment trades on (`simulation`: Shioaji's simulation server in dev and test, the
    real account in prod). A real broker's BUY is then held to its limits (BuyLimitRule).
    """

    brokers: frozenset[ExecutionProvider]
    simulation: bool
    limit_rule: BuyLimitRule

    def apply(
        self, order: Order, run_broker: ExecutionProvider, link: BrokerLink, user: User | None, earlier_buys: Sequence[Order]
    ) -> tuple[RejectReason, str] | None:
        broker = link.broker

        if broker != run_broker:
            return RejectReason.BROKER_NOT_CHOSEN, f"the run chose {run_broker.value}, and this order would reach {broker.value}"

        if broker not in self.brokers:
            return RejectReason.BROKER_NOT_OFFERED, f"this site orders on {', '.join(sorted(self.brokers))} only, not {broker.value}"

        if not broker.real:
            return None

        if user is None or user.status != UserStatus.ACTIVE or Permission.USE_REAL_BROKER not in user.permissions:
            return RejectReason.REAL_BROKER_REFUSED, f"only an active administrator orders on {broker.value}"

        if not link.up:
            return RejectReason.BROKER_LOGIN_DOWN, f"the {broker.value} login is down"

        if link.simulation != self.simulation:
            server = "simulation" if self.simulation else "production"
            return (
                RejectReason.BROKER_SERVER_MISMATCH,
                f"the {broker.value} login is not on the {server} server this environment trades on",
            )

        return self.limit_rule.apply(order, earlier_buys)


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
