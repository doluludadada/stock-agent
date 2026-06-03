from datetime import datetime

from sqlmodel import Field, SQLModel


class Position(SQLModel):
    """Broker/account ownership state."""

    stock_id: str
    quantity: int = Field(gt=0)
    average_cost: float = Field(gt=0)

    opened_at: datetime | None = None
    
    updated_at: datetime = Field(default_factory=datetime.now)
