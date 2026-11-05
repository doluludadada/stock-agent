from datetime import datetime
from typing import Literal, Self

from pydantic import ConfigDict, Field, FiniteFloat, NonNegativeInt, PositiveInt, model_validator, validate_call
from pydantic.dataclasses import dataclass

from a_domain.types.enums import OrderStatus, OrderType, RejectReason, TimeInForce, TradeAction
from a_domain.types.errors import IllegalOrderTransition
from a_domain.types.ids import DecisionId, OrderId, RunId, new_order_id
from a_domain.types.values import NonEmptyText, PositiveFiniteFloat


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
    def _price_matches_order_type(self) -> Self:
        if (self.order_type == OrderType.LIMIT) != (self.limit_price is not None):
            raise ValueError("A LIMIT order needs a limit_price and a MARKET order must not have one")

        return self

    @property
    def remaining_quantity(self) -> int:
        return self.quantity - self.filled_quantity

    @property
    def summary(self) -> str:
        """One log line: the status, what was ordered and filled at what limit, the costs, and the reason when there is one."""
        text = (
            f"{self.status.value.upper()}: {self.action.value.upper()} {self.stock_id} "
            f"filled {self.filled_quantity}/{self.quantity} @ {self.limit_price}, fee={self.fee}, tax={self.tax}"
        )

        return f"{text}, reason={self.reason}" if self.reason else text

    def submit(self, *, now: datetime) -> None:
        """The broker accepted the order."""
        self._move_to(OrderStatus.SUBMITTED, now)

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
        self._check_move(OrderStatus.FILLED)

        if quantity > self.remaining_quantity:
            raise ValueError(f"Fill quantity {quantity} is more than the remaining {self.remaining_quantity}")

        if self.limit_price is not None and self.action == TradeAction.BUY and price > self.limit_price:
            raise ValueError("BUY fill price cannot exceed limit_price")

        if self.limit_price is not None and self.action == TradeAction.SELL and price < self.limit_price:
            raise ValueError("SELL fill price cannot be below limit_price")

        filled_quantity = self.filled_quantity + quantity
        self._move_to(OrderStatus.FILLED if filled_quantity == self.quantity else OrderStatus.SUBMITTED, now)
        self.average_filled_price = ((self.average_filled_price or 0) * self.filled_quantity + price * quantity) / filled_quantity
        self.filled_quantity = filled_quantity
        self.fee += fee
        self.tax += tax

        if realized_pnl is not None:
            self.realized_pnl = (self.realized_pnl or 0) + realized_pnl

    def cancel(self, reason: str, *, now: datetime) -> None:
        self._move_to(OrderStatus.CANCELLED, now, reason)

    def reject(self, reason: RejectReason, detail: str, *, now: datetime) -> None:
        self._move_to(OrderStatus.REJECTED, now, f"{reason.name}: {detail}")

    def fail(self, reason: str, *, now: datetime) -> None:
        self._move_to(OrderStatus.FAILED, now, reason)

    def fail_if_open(self, reason: str, *, now: datetime) -> None:
        """FAILS an order that is still open; an order that already ended keeps its status."""
        if self.status.is_open:
            self.fail(reason, now=now)

    def _check_move(self, status: OrderStatus) -> None:
        if status not in self.status.next_statuses:
            raise IllegalOrderTransition(f"Cannot move order from {self.status} to {status}")

    def _move_to(self, status: OrderStatus, now: datetime, reason: str | None = None) -> None:
        self._check_move(status)

        if status in {OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.FAILED} and not (reason and reason.strip()):
            raise ValueError(f"{status.value.capitalize()} order requires a reason")

        self.status = status
        self.reason = reason
        self.updated_at = now


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
