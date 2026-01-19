from decimal import Decimal
from datetime import datetime
from sqlmodel import SQLModel, Field


class Position(SQLModel):
    """
    Represents the current holding of a specific stock.
    """

    symbol: str = Field(primary_key=True)
    quantity: int = Field(description="Total shares held")
    average_cost: Decimal = Field(decimal_places=2)
    current_price: Decimal | None = Field(default=None, decimal_places=2)

    # PnL Calculation (Unrealized)
    unrealized_profit: Decimal | None = Field(default=None)

    last_updated: datetime = Field(default_factory=datetime.now)
