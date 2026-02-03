from datetime import datetime
from decimal import Decimal

from sqlmodel import Field, SQLModel


class Position(SQLModel):
    """
    Represents a stock currently held in the portfolio.
    """

    stock_id: str = Field(primary_key=True)
    quantity: int = Field(gt=0)
    average_cost: Decimal = Field(decimal_places=2)

    # Updated by Market Data
    current_price: Decimal = Field(default=0, decimal_places=2)
    market_value: Decimal = Field(default=0, decimal_places=2)

    last_updated: datetime = Field(default_factory=datetime.now)

    @property
    def unrealized_pnl(self) -> Decimal:
        if self.quantity == 0:
            return Decimal(0)
        return (self.current_price - self.average_cost) * self.quantity


