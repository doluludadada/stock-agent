from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from src.a_domain.types.enums import OrderAction, OrderStatus, OrderType


class Order(SQLModel):
    """
    Represents an instruction to the broker.
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    stock_id: str
    action: OrderAction  # BUY/SELL
    order_type: OrderType  # MARKET/LIMIT
    price: Decimal | None = None
    quantity: int

    status: OrderStatus = Field(default=OrderStatus.PENDING)
    created_at: datetime = Field(default_factory=datetime.now)
