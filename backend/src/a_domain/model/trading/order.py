import math
from collections.abc import Mapping
from datetime import datetime
from typing import Literal, Self

from pydantic import model_validator
from sqlmodel import Field, SQLModel

from a_domain.rules.trading.cost import TradeCost
from a_domain.rules.trading.tick import TickRule
from a_domain.types.enums import OrderStatus, OrderType, RejectReason, TimeInForce, TradeAction
from a_domain.types.errors import IllegalOrderTransition
from a_domain.types.ids import DecisionId, OrderId, RunId, new_order_id

ORDER_TRANSITIONS: Mapping[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING: frozenset({OrderStatus.SUBMITTED, OrderStatus.REJECTED, OrderStatus.FAILED, OrderStatus.CANCELLED}),
    OrderStatus.SUBMITTED: frozenset({OrderStatus.SUBMITTED, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.FAILED}),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.FAILED: frozenset(),
}
"""
Every legal status change. SUBMITTED -> SUBMITTED is a partial fill that leaves the rest working.

- PENDING: built by the app, not yet accepted by a broker.
- SUBMITTED: accepted and working; may hold a partial fill.
- FILLED: the whole quantity executed.
- CANCELLED: stopped before the whole quantity executed (by a cancel, an IOC remainder, or a FOK kill); may hold a partial fill.
- REJECTED: refused by a business or validation rule before acceptance (gate refused, invalid order, insufficient cash or shares).
- FAILED: a technical error (exception, broker unreachable), whatever state the order was in.
"""


class Order(SQLModel):
    """
    The app's record of one order: the decision it executes, what went to (or was refused before)
    the broker, and how it ended. OrderExecution saves it in the `orders` table whichever provider ran it.
    """

    id: OrderId = Field(default_factory=new_order_id)
    run_id: RunId
    decision_id: DecisionId

    stock_id: str = Field(min_length=1)
    action: Literal[TradeAction.BUY, TradeAction.SELL]
    order_type: OrderType
    quantity: int = Field(gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    time_in_force: TimeInForce

    status: OrderStatus = OrderStatus.PENDING
    reason: str | None = None

    filled_quantity: int = Field(default=0, ge=0)
    average_filled_price: float | None = Field(default=None, gt=0)
    fee: int = Field(default=0, ge=0)
    tax: int = Field(default=0, ge=0)
    realized_pnl: float | None = None
    """SELL only: proceeds net of fee and tax minus the cost basis (buy fees included) of the shares sold."""

    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _price_matches_order_type(self) -> Self:
        if (self.order_type == OrderType.LIMIT) != (self.limit_price is not None):
            raise ValueError("A LIMIT order needs a limit_price and a MARKET order must not have one")

        if self.limit_price is not None and not TickRule.is_tick(self.stock_id, self.limit_price):
            raise ValueError(f"limit_price {self.limit_price!r} is not an exchange tick for {self.stock_id}")

        return self

    @property
    def remaining_quantity(self) -> int:
        return self.quantity - self.filled_quantity

    def submit(self, *, now: datetime) -> None:
        """The broker accepted the order."""
        self._move_to(OrderStatus.SUBMITTED, now)

    def fill(self, quantity: int, price: float, cost: TradeCost, realized_pnl: float | None = None, *, now: datetime) -> None:
        """Records one execution. The order becomes FILLED when nothing remains, otherwise it keeps working."""
        self._check_move(OrderStatus.FILLED)

        if not 0 < quantity <= self.remaining_quantity:
            raise ValueError(f"Fill quantity {quantity} must be between 1 and the remaining {self.remaining_quantity}")

        if not math.isfinite(price) or price <= 0:
            raise ValueError("Filled price must be positive")

        if cost.action != self.action:
            raise ValueError(f"{cost.action} cost cannot settle a {self.action} order")

        if self.limit_price is not None and self.action == TradeAction.BUY and price > self.limit_price:
            raise ValueError("BUY fill price cannot exceed limit_price")

        if self.limit_price is not None and self.action == TradeAction.SELL and price < self.limit_price:
            raise ValueError("SELL fill price cannot be below limit_price")

        filled_quantity = self.filled_quantity + quantity
        self._move_to(OrderStatus.FILLED if filled_quantity == self.quantity else OrderStatus.SUBMITTED, now)

        self.average_filled_price = ((self.average_filled_price or 0) * self.filled_quantity + price * quantity) / filled_quantity
        self.filled_quantity = filled_quantity
        self.fee += cost.fee
        self.tax += cost.tax

        if realized_pnl is not None:
            self.realized_pnl = (self.realized_pnl or 0) + realized_pnl

    def cancel(self, reason: str, *, now: datetime) -> None:
        self._move_to(OrderStatus.CANCELLED, now, reason)

    def reject(self, reason: RejectReason, detail: str, *, now: datetime) -> None:
        self._move_to(OrderStatus.REJECTED, now, f"{reason.name}: {detail}")

    def fail(self, reason: str, *, now: datetime) -> None:
        self._move_to(OrderStatus.FAILED, now, reason)

    def _check_move(self, status: OrderStatus) -> None:
        if status not in ORDER_TRANSITIONS[self.status]:
            raise IllegalOrderTransition(f"Cannot move order from {self.status} to {status}")

    def _move_to(self, status: OrderStatus, now: datetime, reason: str | None = None) -> None:
        self._check_move(status)

        if status in {OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.FAILED} and not (reason and reason.strip()):
            raise ValueError(f"{status.value.capitalize()} order requires a reason")

        self.status = status
        self.reason = reason
        self.updated_at = now
