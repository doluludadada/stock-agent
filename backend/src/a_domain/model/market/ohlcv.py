from datetime import datetime
from decimal import Decimal

from sqlmodel import Field, SQLModel


class Ohlcv(SQLModel):
    """
    Represents a single candlestick (K-Bar).
    """

    ts: datetime = Field(description="Timestamp of the candle")
    open_price: Decimal = Field(default=0, decimal_places=2)
    high_price: Decimal = Field(default=0, decimal_places=2)
    low_price: Decimal = Field(default=0, decimal_places=2)
    close_price: Decimal = Field(default=0, decimal_places=2)
    volume: int = Field(default=0)

    # Optional: Adjusted close for backtesting accuracy
    adj_close: Decimal | None = Field(default=None, decimal_places=2)


