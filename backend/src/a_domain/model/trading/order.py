import math
from collections.abc import Sequence
from datetime import datetime
from typing import Literal, Self

from pydantic import ConfigDict, Field, FiniteFloat, NonNegativeInt, PositiveInt, model_validator, validate_call
from pydantic.dataclasses import dataclass

from a_domain.types.enums import OrderStatus, OrderType, RejectReason, TimeInForce, TradeAction
from a_domain.types.errors import IllegalOrderTransition
from a_domain.types.ids import DecisionId, OrderId, RunId, new_order_id
from a_domain.types.values import NonEmptyText, PositiveFiniteFloat


def volume_weighted_price(deals: Sequence[tuple[float, int]]) -> float | None:
    """
    The volume-weighted price of `deals`, each (price, quantity), or None while none of them dealt. It never leaves the
    range of their own prices, which a float's rounding of the average can (12.45 x 329 / 329 is 12.450000000000001):
    deals at one price fill at exactly it, so a BUY whose deals are at or under its limit never fills above it, nor a
    SELL under it.
    """
    dealt = [(price, quantity) for price, quantity in deals if quantity]

    if not dealt:
        return None

    prices = [price for price, _ in dealt]
    average = math.fsum(price * quantity for price, quantity in dealt) / sum(quantity for _, quantity in dealt)
    return min(max(average, min(prices)), max(prices))


def check_move(order: Order, status: OrderStatus) -> None:
    if status not in order.status.next_statuses:
        raise IllegalOrderTransition(f"Cannot move order from {order.status} to {status}")


def move_to(order: Order, status: OrderStatus, now: datetime, reason: str | None = None) -> None:
    check_move(order, status)

    if status in {OrderStatus.UNCONFIRMED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.FAILED} and not (
        reason and reason.strip()
    ):
        raise ValueError(f"{status.value.capitalize()} order requires a reason")

    order.status = status
    order.reason = reason
    order.updated_at = now


@dataclass(config=ConfigDict(validate_assignment=True, json_schema_serialization_defaults_required=True), kw_only=True)
class Order:
    """
    The app's record of one order: the decision it executes, what went to (or was refused before)
    the broker, and how it ended. OrderPreparation saves it in the `orders` table before it is sent, and OrderExecution
    saves the broker's answer, whichever provider ran it.
    """

    id: OrderId = Field(default_factory=new_order_id)
    run_id: RunId
    decision_id: DecisionId

    stock_id: NonEmptyText
    action: Literal[TradeAction.BUY, TradeAction.SELL]
    order_type: OrderType
    quantity: PositiveInt
    limit_price: PositiveFiniteFloat | None = None
    price_at_signal: PositiveFiniteFloat
    """
    The price its decision saw (TradeSignal.price_at_signal), which its limit lies at most trading.limit_offset_pct past
    (LimitPriceRule): the market's price where the mock account fills it, and what a broker's fill compares with.
    """
    time_in_force: TimeInForce

    status: OrderStatus = OrderStatus.PENDING
    reason: str | None = None

    filled_quantity: NonNegativeInt = 0
    average_filled_price: PositiveFiniteFloat | None = None
    fee: NonNegativeInt = 0
    tax: NonNegativeInt = 0
    realized_pnl: float | None = None
    """SELL only: proceeds net of fee and tax minus the cost basis (buy fees included) of the shares sold."""

    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def price_matches_order_type(self) -> Self:
        if (self.order_type == OrderType.LIMIT) != (self.limit_price is not None):
            raise ValueError("A LIMIT order needs a limit_price and a MARKET order must not have one")

        return self

    @property
    def remaining_quantity(self) -> int:
        return self.quantity - self.filled_quantity

    @property
    def summary(self) -> str:
        """
        One log line: the status, what was ordered and filled, at the average filled price once something filled and
        at the limit before, the costs, and the reason when there is one.
        """
        price = self.average_filled_price if self.filled_quantity else self.limit_price
        text = (
            f"{self.status.value.upper()}: {self.action.value.upper()} {self.stock_id} "
            f"filled {self.filled_quantity}/{self.quantity} @ {price}, fee={self.fee}, tax={self.tax}"
        )

        return f"{text}, reason={self.reason}" if self.reason else text

    def tag(self, part: int) -> str:
        """
        The tag of the order's part `part` (its index among the parts LotSplitRule splits it into) at a real broker, a
        broker order's custom field: the id's first five hex digits and the index, which a person finds in the
        broker's order history.
        """
        return f"{self.id.hex[:5]}{part}"

    def submit(self, *, now: datetime) -> None:
        """The broker accepted the order."""
        move_to(self, OrderStatus.SUBMITTED, now)

    @validate_call
    def fill(
        self,
        quantity: PositiveInt,
        price: PositiveFiniteFloat,
        fee: NonNegativeInt,
        tax: NonNegativeInt,
        realized_pnl: FiniteFloat | None = None,
        *,
        now: datetime,
    ) -> None:
        """Records one execution and what it cost. The order becomes FILLED when nothing remains, otherwise it keeps working."""
        check_move(self, OrderStatus.FILLED)

        if quantity > self.remaining_quantity:
            raise ValueError(f"Fill quantity {quantity} is more than the remaining {self.remaining_quantity}")

        if self.limit_price is not None and self.action == TradeAction.BUY and price > self.limit_price:
            raise ValueError("BUY fill price cannot exceed limit_price")

        if self.limit_price is not None and self.action == TradeAction.SELL and price < self.limit_price:
            raise ValueError("SELL fill price cannot be below limit_price")

        filled_quantity, held = self.filled_quantity + quantity, (self.average_filled_price or price, self.filled_quantity)
        move_to(self, OrderStatus.FILLED if filled_quantity == self.quantity else OrderStatus.SUBMITTED, now)
        self.average_filled_price = volume_weighted_price([held, (price, quantity)])
        self.filled_quantity = filled_quantity
        self.fee += fee
        self.tax += tax

        if realized_pnl is not None:
            self.realized_pnl = (self.realized_pnl or 0) + realized_pnl

    def cancel(self, reason: str, *, now: datetime) -> None:
        move_to(self, OrderStatus.CANCELLED, now, reason)

    def reject(self, reason: RejectReason, detail: str, *, now: datetime) -> None:
        move_to(self, OrderStatus.REJECTED, now, f"{reason.name}: {detail}")

    def fail(self, reason: str, *, now: datetime) -> None:
        move_to(self, OrderStatus.FAILED, now, reason)

    def leave_unconfirmed(self, reason: str, *, now: datetime) -> None:
        """Sent to a real broker whose outcome the site could not read: the broker's own record of the day settles it."""
        move_to(self, OrderStatus.UNCONFIRMED, now, reason)

    def drop_realized_pnl(self, why: str) -> None:
        """
        A SELL whose realized PnL could not be computed for every share it sold keeps none, not even what an earlier
        part realized, and its reason, which a FILLED order otherwise has none of, says why.
        """
        self.realized_pnl = None
        self.reason = f"{self.reason}; {why}" if self.reason else why

    def fail_if_open(self, reason: str, *, now: datetime) -> None:
        """
        FAILS an order that is still open; an order that already ended keeps its status, and so does one that awaits
        settlement, whose outcome the broker's record gives later.
        """
        if self.status.is_open and not self.status.awaits_settlement:
            self.fail(reason, now=now)
