from datetime import datetime
from typing import ClassVar

from sqlmodel import Field, SQLModel

from c_infrastructure.database.utc_datetime import UtcDateTime


class ManualHoldingDTO(SQLModel, table=True):
    """One holding a user entered by hand: shares of one stock at their average cost, on one owner's list."""

    __tablename__: ClassVar[str] = "manual_holdings"

    owner_id: str = Field(primary_key=True)
    stock_id: str = Field(primary_key=True)
    quantity: int
    average_cost: float
    opened_at: datetime | None = Field(default=None, sa_type=UtcDateTime)
