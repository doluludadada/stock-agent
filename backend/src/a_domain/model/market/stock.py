from sqlmodel import Field, SQLModel

from backend.src.a_domain.types.enums import MarketType


class Stock(SQLModel):
    stock_id: str = Field(min_length=1, max_length=10, primary_key=True)
    market: MarketType
    name: str | None = None
    industry: str | None = None
