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
