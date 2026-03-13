from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from a_domain.types.enums import OrderStatus, OrderType, TradeAction


class Order(SQLModel):
    """Represents an instruction to the broker."""

    id: UUID = Field(default_factory=uuid4)
    stock_id: str
    action: TradeAction
    order_type: OrderType
    price: float | None = None
    quantity: int
    status: OrderStatus = Field(default=OrderStatus.PENDING)
    created_at: datetime = Field(default_factory=datetime.now)
