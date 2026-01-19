from sqlmodel import SQLModel, Field
from src.a_domain.types.enums import MarketType


class Stock(SQLModel):
    """
    Represents a basic stock entity (Symbol/Ticker).
    """

    symbol: str = Field(min_length=1, max_length=10, index=True)
    market: MarketType
    name: str | None = None
    industry: str | None = None
    currency: str = Field(default="TWD")
