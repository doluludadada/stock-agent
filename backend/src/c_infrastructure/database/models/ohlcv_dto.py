from datetime import date, datetime
from typing import ClassVar

from pydantic import model_validator
from sqlmodel import Field, SQLModel

from c_infrastructure.database.utc_datetime import UtcDateTime


class OhlcvDTO(SQLModel, table=True):
    """One cached daily bar (Ohlcv). A bar is stamped at its session's close, so (stock_id, ts) is one row per stock and session."""

    __tablename__: ClassVar[str] = "ohlcv_data"

    # The columns keep the order the table was created with, so its primary key stays (ts, stock_id).
    ts: datetime = Field(primary_key=True, sa_type=UtcDateTime, description="Timestamp of the candle")
    open: float = 0
    high: float = 0
    low: float = 0
    close: float = 0
    volume: int = 0
    adj_close: float | None = None
    stock_id: str = Field(primary_key=True)

    @model_validator(mode="after")
    def _check_invariants(self) -> OhlcvDTO:
        assert self.open >= 0, "open must be non-negative"
        assert self.high >= 0, "high must be non-negative"
        assert self.low >= 0, "low must be non-negative"
        assert self.close >= 0, "close must be non-negative"
        assert self.volume >= 0, "volume must be non-negative"
        if self.high > 0 and self.low > 0:
            assert self.high >= self.low, "high must be >= low"
        return self


class OhlcvFetchDTO(SQLModel, table=True):
    """The last time the history source was asked for one stock's daily bars, and the last settled session at that time."""

    __tablename__: ClassVar[str] = "ohlcv_fetches"

    stock_id: str = Field(primary_key=True)
    fetched_at: datetime = Field(sa_type=UtcDateTime)
    settled_session: date


class OhlcvWindowDTO(SQLModel, table=True):
    """
    The earliest session the history source was ever asked for, per stock. A window that starts earlier than it is
    fetched again, so a longer strategy gets its older bars; a stock whose history is short is not asked again.
    """

    __tablename__: ClassVar[str] = "ohlcv_windows"

    stock_id: str = Field(primary_key=True)
    first_session: date
