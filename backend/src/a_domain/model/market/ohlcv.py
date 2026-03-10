from datetime import datetime

from pydantic import BaseModel, Field


class Ohlcv(BaseModel):
    ts: datetime = Field(description="Timestamp of the candle")
    open: float = Field(default=0)
    high: float = Field(default=0)
    low: float = Field(default=0)
    close: float = Field(default=0)
    volume: int = Field(default=0)
    adj_close: float | None = Field(default=None)
