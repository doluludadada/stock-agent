from datetime import datetime

from pydantic import BaseModel, Field


class Position(BaseModel):
    """Represents a stock currently held in the portfolio."""

    stock_id: str
    quantity: int = Field(gt=0)
    average_cost: float

    current_price: float = 0
    market_value: float = 0

    last_updated: datetime = Field(default_factory=datetime.now)

    @property
    def unrealized_pnl(self) -> float:
        if self.quantity == 0:
            return 0.0
        return (self.current_price - self.average_cost) * self.quantity
