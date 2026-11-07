from datetime import datetime

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass


@dataclass(frozen=True, config=ConfigDict(json_schema_serialization_defaults_required=True, use_attribute_docstrings=True))
class Ohlcv:
    """
    One bar of trading. A daily bar is stamped at its session's 13:30 close in Asia/Taipei, and its volume is in shares.
    Every field is in every answer, so the Web API's schema requires each one.
    """

    ts: datetime = Field(description="Timestamp of the candle")
    open: float = 0
    high: float = 0
    low: float = 0
    close: float = 0
    volume: int = 0
    change: float | None = None
    """
    The exchange's official change from the session's reference price: the previous close, adjusted on an ex-rights or
    ex-dividend day. The exchanges' daily reports and listings and the broker's snapshots report it; a bar without one,
    or whose exchange compared its close to no reference, has None.
    """
