from sqlmodel import Field, SQLModel


class PositionSnapshot(SQLModel):
    """One position at snapshot time, marked at the latest price the run knew for it."""

    stock_id: str
    quantity: int = Field(gt=0)
    average_cost: float = Field(gt=0)
    mark_price: float = Field(gt=0)

    @property
    def market_value(self) -> float:
        return self.quantity * self.mark_price
