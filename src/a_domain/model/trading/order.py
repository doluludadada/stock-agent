from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field
from src.a_domain.types.enums import OrderAction, OrderStatus, OrderType, TimeInForce


class Order(SQLModel):
    """
    Represents a trading order instruction.
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    symbol: str = Field(index=True)
    action: OrderAction
    order_type: OrderType = Field(default=OrderType.LIMIT)
    price: Decimal | None = Field(default=None, description="Required for LIMIT orders")
    quantity: int = Field(gt=0)
    time_in_force: TimeInForce = Field(default=TimeInForce.ROD)

    status: OrderStatus = Field(default=OrderStatus.PENDING)

    # Audit trail
    broker_order_id: str | None = Field(
        default=None, description="ID returned by the broker infra"
    )
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
