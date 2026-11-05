from datetime import datetime

from pydantic import Field
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class Ohlcv:
    ts: datetime = Field(description="Timestamp of the candle")
    open: float = 0
    high: float = 0
    low: float = 0
    close: float = 0
    volume: int = 0
    adj_close: float | None = None
    change: float | None = None
    """
    The exchange's official change from the session's reference price: the previous close, adjusted on an ex-rights or
    ex-dividend day. Only the TWSE and TPEX listings report it; a bar from another source has None.
    """
