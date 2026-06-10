from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from a_domain.types.enums import OrderStatus, OrderType, TimeInForce, TradeAction


class Order(SQLModel):
    """Represents an instruction to the broker."""

    id: UUID = Field(default_factory=uuid4)

    stock_id: str
    action: TradeAction
    order_type: OrderType
    quantity: int

    limit_price: float | None = None
    average_filled_price: float | None = None
    time_in_force: TimeInForce = TimeInForce.ROD

    status: OrderStatus = OrderStatus.PENDING
    reason: str | None = None

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)