from datetime import date, datetime
from typing import ClassVar

from pydantic import model_validator
from sqlalchemy import BigInteger
from sqlmodel import Field, SQLModel

from c_infrastructure.database.utc_datetime import UtcDateTime


class OhlcvDTO(SQLModel, table=True):
    """
    One daily bar (Ohlcv) of a personal site's history cache, as its broker served it: a stock's under its stock_id,
    an exchange's own index under `^` and its market. A bar is stamped at its session's close, so (stock_id, ts) is one
    row per stock and session. Never an open-data archive table: the broker's data may not be redistributed.
    """

    __tablename__: ClassVar[str] = "ohlcv_data"

    stock_id: str = Field(primary_key=True)
    ts: datetime = Field(primary_key=True, index=True, sa_type=UtcDateTime, description="Timestamp of the candle")
    """Indexed on its own: the primary key leads with stock_id, and a sync asks which sessions hold any stock."""

    open: float = 0
    high: float = 0
    low: float = 0
    close: float = 0
    volume: int = Field(default=0, sa_type=BigInteger)
    """Shares traded. An ETF has traded over a billion in a session, and an index's session many more."""
    change: float | None = None

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


class ExRightReferenceDTO(SQLModel, table=True):
    """
    TWSE's reference price of a stock on one of its ex-right or ex-dividend days, as its TWT49U report listed it: the
    price the history cache's bar of that session compares its close to where the closing quotes give no change.
    """

    __tablename__: ClassVar[str] = "ex_right_references"

    stock_id: str = Field(primary_key=True)
    session_date: date = Field(primary_key=True, index=True)
    """Indexed on its own: a sync asks for the earliest and the latest day the cache holds."""

    reference_price: float
