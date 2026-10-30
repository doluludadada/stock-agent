from datetime import date, datetime
from typing import ClassVar

from pydantic import model_validator
from sqlmodel import Field, SQLModel

from a_domain.model.market.ohlcv import Ohlcv


class OhlcvDTO(Ohlcv, table=True):
    """One cached daily bar. A bar is stamped at its session's close, so (stock_id, ts) is one row per stock and session."""

    __tablename__: ClassVar[str] = "ohlcv_data"  # pyright: ignore[reportIncompatibleVariableOverride]

    stock_id: str = Field(primary_key=True)
    ts: datetime = Field(primary_key=True, description="Timestamp of the candle")

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

    __tablename__: ClassVar[str] = "ohlcv_fetches"  # pyright: ignore[reportIncompatibleVariableOverride]

    stock_id: str = Field(primary_key=True)
    fetched_at: datetime
    settled_session: date
