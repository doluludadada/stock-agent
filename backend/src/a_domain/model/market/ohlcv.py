from datetime import datetime
from decimal import Decimal

from sqlmodel import Field, SQLModel


class Ohlcv(SQLModel):
    ts: datetime = Field(description="Timestamp of the candle")
    open: Decimal = Field(default=0, decimal_places=2)
    high: Decimal = Field(default=0, decimal_places=2)
    low: Decimal = Field(default=0, decimal_places=2)
    close: Decimal = Field(default=0, decimal_places=2)
    volume: int = Field(default=0)
    adj_close: Decimal | None = Field(default=None, decimal_places=2)
