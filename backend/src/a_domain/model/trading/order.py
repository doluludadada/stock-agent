import math
from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from a_domain.types.enums import OrderStatus, OrderType, TimeInForce, TradeAction


class Order(SQLModel):
    """Represents a broker order and its current execution state."""

    id: UUID = Field(default_factory=uuid4)

    stock_id: str = Field(min_length=1)
    action: TradeAction
    order_type: OrderType
    quantity: int = Field(gt=0)

    limit_price: float | None = Field(default=None, gt=0)
    average_filled_price: float | None = Field(
        default=None,
        gt=0,
    )
    time_in_force: TimeInForce = TimeInForce.ROD

    status: OrderStatus = OrderStatus.PENDING
    reason: str | None = None

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # ---------------------------------------------------------------------------- #
    #                                   Functions                                  #
    # ---------------------------------------------------------------------------- #
    def validate_submission(self) -> None:
        if self.status != OrderStatus.PENDING:
            raise ValueError(f"Cannot submit order from status {self.status}")

        if self.action == TradeAction.HOLD:
            raise ValueError("HOLD is not an executable order action")

        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("LIMIT order requires limit_price")

        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("MARKET order must not contain limit_price")

        if self.average_filled_price is not None:
            raise ValueError("New order must not contain average_filled_price")

        if self.reason is not None:
            raise ValueError("New order must not contain a terminal reason")

    def submit(self) -> None:
        self.validate_submission()

        self.status = OrderStatus.SUBMITTED
        self.reason = None
        self.updated_at = datetime.now()

    def fill(
        self,
        filled_price: float,
    ) -> None:
        if self.status not in {
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
        }:
            raise ValueError(f"Cannot fill order from status {self.status}")

        if not math.isfinite(filled_price) or filled_price <= 0:
            raise ValueError("Filled price must be positive")

        if self.order_type == OrderType.LIMIT:
            if self.limit_price is None:
                raise ValueError("LIMIT order requires limit_price")

            if self.action == TradeAction.BUY and filled_price > self.limit_price:
                raise ValueError("BUY fill price cannot exceed limit_price")

            if self.action == TradeAction.SELL and filled_price < self.limit_price:
                raise ValueError("SELL fill price cannot be below limit_price")

        self.status = OrderStatus.FILLED
        self.average_filled_price = filled_price
        self.reason = None
        self.updated_at = datetime.now()

    def cancel(self) -> None:
        if self.status != OrderStatus.SUBMITTED:
            raise ValueError(f"Cannot cancel order from status {self.status}")

        self.status = OrderStatus.CANCELLED
        self.reason = None
        self.updated_at = datetime.now()

    def reject(
        self,
        reason: str,
    ) -> None:
        if self.status != OrderStatus.PENDING:
            raise ValueError(f"Cannot reject order from status {self.status}")

        if not reason.strip():
            raise ValueError("Rejected order requires a reason")

        self.status = OrderStatus.REJECTED
        self.reason = reason
        self.updated_at = datetime.now()

    def fail(
        self,
        reason: str,
    ) -> None:
        if self.status not in {
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
        }:
            raise ValueError(f"Cannot fail order from status {self.status}")

        if not reason.strip():
            raise ValueError("Failed order requires a reason")

        self.status = OrderStatus.FAILED
        self.reason = reason
        self.updated_at = datetime.now()
