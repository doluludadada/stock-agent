import math
from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import PositiveInt, validate_call
from pydantic.dataclasses import dataclass

from a_domain.model.trading.account import Account, BrokerFill, Position
from a_domain.model.trading.order import Order
from a_domain.rules.trading.cost import TradeCost, TradingCostRule
from a_domain.types.enums import LotKind, OrderStatus, OrderType, RejectReason, TimeInForce, TradeAction
from a_domain.types.values import PositiveFiniteFloat


@dataclass(frozen=True)
class OrderAcceptanceRule:
    """
    Why a broker adapter refuses an order from `account` before the broker sees it, whichever broker it is, or None.
    The app tracks no working orders, so it sends only LIMIT orders whose unfilled part ends at once: IOC or FOK, never
    ROD. Then a broker's pre-trade check at the limit price: a BUY needs the cash for the whole quantity plus fee, a SELL
    needs the shares.
    """

    cost_rule: TradingCostRule

    def apply(self, order: Order, account: Account) -> tuple[RejectReason, str] | None:
        if order.order_type != OrderType.LIMIT or order.limit_price is None:
            return RejectReason.UNSUPPORTED_ORDER_TYPE, "the app sends LIMIT orders only"

        if order.time_in_force not in {TimeInForce.IOC, TimeInForce.FOK}:
            return (
                RejectReason.UNSUPPORTED_TIME_IN_FORCE,
                f"{order.time_in_force.name} would leave a working order at the broker that the app does not track",
            )

        if order.action == TradeAction.BUY:
            cost = self.cost_rule.apply(TradeAction.BUY, order.stock_id, order.limit_price, order.quantity, now=order.created_at)
            needed = -cost.net
            refusal = RejectReason.INSUFFICIENT_CASH, f"needs {needed:,.0f} including fee, cash is {account.cash:,.0f}"
            return None if account.can_afford(needed) else refusal

        position = account.position_for(order.stock_id)

        if position is None:
            return RejectReason.POSITION_NOT_FOUND, f"no {order.stock_id} shares held"

        if not position.can_cover(order.quantity):
            return RejectReason.INSUFFICIENT_POSITION, f"holds {position.quantity}, selling {order.quantity}"

        return None


@dataclass(frozen=True)
class SimulationCashRule:
    """
    The cash of a real broker's account on its simulation server, which reports no balance: the cash the account
    started with, minus what its stocks cost, plus the profit and loss its sales realized. `simulation_initial_cash` is
    a setting; every other figure is the broker's own record of the account, so the positions are held once, at the
    broker.

    A stock's position does not list the BUYs of it dealt today yet while it holds no more shares than the broker says
    the account held at yesterday's close (`held_yesterday`), so the stock costs its position and those BUYs. Once the
    position holds more it lists them, and the stock costs the larger of the two: a BUY listed both ways counts once,
    and a stock bought new today whose position lists only part of the day's BUYs still counts them whole. Two BUYs in
    a row then never spend the same cash. A stock also sold today can count a listed BUY twice, which understates the
    cash; one topped up today whose position lists only part of the day's BUYs counts the larger of the two, which can
    overstate it. `sales` are every sale the broker lists, each with the profit or loss the broker says it realized,
    taken as what the sale brought after both trades' fees and its tax. A position's cost is taken as what the broker
    says the shares cost.

    The answer is below zero when the records say the account spent more than it started with: the setting was lowered
    under what the account holds, or the broker's figures are not what this rule takes them for.
    """

    simulation_initial_cash: PositiveFiniteFloat

    def apply(
        self,
        positions: Sequence[Position],
        held_yesterday: Mapping[str, int],
        bought_today: Mapping[str, float],
        sales: Sequence[BrokerFill],
    ) -> float:
        shares: dict[str, int] = {}
        held: dict[str, float] = {}

        for position in positions:
            shares[position.stock_id] = shares.get(position.stock_id, 0) + position.quantity
            held[position.stock_id] = held.get(position.stock_id, 0.0) + position.cost_basis

        stocks_cost = math.fsum(
            max(held.get(stock_id, 0.0), bought_today.get(stock_id, 0.0))
            if shares.get(stock_id, 0) > held_yesterday.get(stock_id, 0)
            else held.get(stock_id, 0.0) + bought_today.get(stock_id, 0.0)
            for stock_id in held.keys() | bought_today.keys()
        )
        realized_pnl = math.fsum(sale.realized_pnl or 0.0 for sale in sales)

        return self.simulation_initial_cash - stocks_cost + realized_pnl


@dataclass(frozen=True)
class LotSplitRule:
    """
    Splits an order's quantity into what the exchange trades: the whole board lots as one board-lot part and the rest
    as one odd-lot part, each as (kind, shares). With 1000-share lots, 2500 shares are 2000 board-lot shares plus 500
    odd shares.
    """

    board_lot_shares: int

    @validate_call
    def apply(self, quantity: PositiveInt) -> list[tuple[LotKind, int]]:
        odd_shares = quantity % self.board_lot_shares
        parts = ((LotKind.BOARD_LOT, quantity - odd_shares), (LotKind.ODD_LOT, odd_shares))

        return [(kind, shares) for kind, shares in parts if shares]


@dataclass(frozen=True)
class FillRule:
    """
    What one fill of an order settles: the fee and tax of its shares at its price on the fill's date (TradingCostRule)
    and, for a SELL of shares the account holds, the realized PnL against their cost basis (Position.profit_on_sale).
    """

    cost_rule: TradingCostRule

    def apply(
        self, order: Order, quantity: int, price: float, held: Position | None, *, now: datetime
    ) -> tuple[TradeCost, float | None]:
        cost = self.cost_rule.apply(order.action, order.stock_id, price, quantity, now=now)

        if order.action == TradeAction.SELL and held is not None:
            return cost, held.profit_on_sale(quantity, cost.net)

        return cost, None


@dataclass(frozen=True, kw_only=True)
class ExchangeOrder:
    """
    One exchange order, a part of an Order: a domain order goes to the exchange as one exchange order per lot part
    (round lots and an odd-lot remainder). It says where that part is in the order lifecycle and what executed so far,
    in shares, as the broker reported it.
    """

    stock_id: str
    status: OrderStatus
    ordered_shares: int

    dealt_shares: int
    """The shares in the broker's list of deals, which is what an order records as filled."""

    reported_dealt_shares: int
    """The shares the broker's status counts as dealt. More than dealt_shares while deals are still on their way."""

    fill_price: float | None
    """The deals' volume-weighted price. None while nothing is dealt."""

    description: str
    """The broker's own words for the exchange order, for logs and for the reason the order ends with."""

    @property
    def deals_missing(self) -> bool:
        """The deals cannot be the whole story: fewer than the broker counts, or fewer than a FILLED order's quantity."""
        if self.dealt_shares < self.reported_dealt_shares:
            return True

        return self.status == OrderStatus.FILLED and self.dealt_shares < self.ordered_shares


@dataclass(frozen=True)
class BrokerOutcomeRule:
    """
    The final status of an order a real broker took as one exchange order per lot part, once the parts it sent have
    reported. A FILLED order stays FILLED. Otherwise:
    - A part still working after a cancel request FAILS the order: the broker may still fill it, so `broker` is
      named as the place to check.
    - A part the broker ended as FAILED, or whose deals cannot be the whole story, FAILS the order instead of guessing
      what executed.
    - Nothing filled and every part refused: REJECTED as BROKER_REFUSED.
    - Anything else is CANCELLED with what filled: an IOC remainder, a FOK kill, or a refused part.
    `unsent` says why the parts after those were never sent, when the site refused one right before its send.
    """

    broker: str

    def apply(self, order: Order, parts: Sequence[ExchangeOrder], now: datetime, unsent: str | None = None) -> None:
        if order.status == OrderStatus.FILLED:
            return

        rest = [f"the rest was not sent: {unsent}"] if unsent is not None else []
        summary = "; ".join([*(part.description for part in parts), *rest])

        if any(part.status.is_open for part in parts):
            order.fail(f"still working at the broker after a cancel request, check {self.broker}: {summary}", now=now)
            return

        if any(part.status == OrderStatus.FAILED or part.deals_missing for part in parts):
            order.fail(f"unexplained broker result: {summary}", now=now)
            return

        if order.filled_quantity == 0 and all(part.status == OrderStatus.REJECTED for part in parts):
            order.reject(RejectReason.BROKER_REFUSED, summary, now=now)
            return

        order.cancel(f"{order.time_in_force.name} unfilled: filled {order.filled_quantity} of {order.quantity}; {summary}", now=now)
