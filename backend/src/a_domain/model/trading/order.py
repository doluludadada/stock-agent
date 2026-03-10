from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from a_domain.types.enums import OrderAction, OrderStatus, OrderType


# I think order, position and singal can be combined or something.
class Order(BaseModel):
    """Represents an instruction to the broker."""

    id: UUID = Field(default_factory=uuid4)
    stock_id: str
    action: OrderAction
    order_type: OrderType
    price: float | None = None
    quantity: int
    status: OrderStatus = Field(default=OrderStatus.PENDING)
    created_at: datetime = Field(default_factory=datetime.now)
