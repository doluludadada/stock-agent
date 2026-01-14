from datetime import datetime
from decimal import Decimal
from sqlmodel import SQLModel, Field


class Ohlcv(SQLModel):
    ts: datetime = Field(description="Timestamp of the candle")
    open_price: Decimal = Field(default=0, decimal_places=2)
    high_price: Decimal = Field(default=0, decimal_places=2)
    low_price: Decimal = Field(default=0, decimal_places=2)
    close_price: Decimal = Field(default=0, decimal_places=2)
    volume: int = Field(default=0)

    # Adjusted close is crucial for historical analysis
    adj_close: Decimal | None = Field(default=None, decimal_places=2)
