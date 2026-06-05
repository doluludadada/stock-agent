from datetime import date, datetime
from typing import ClassVar

from pydantic import model_validator
from sqlmodel import Field

from a_domain.model.market.ohlcv import Ohlcv


# TODO: Think about 3NF, there's two PKs
class OhlcvDTO(Ohlcv, table=True):
    """Infrastructure Database Model for Caching OHLCV Data."""

    __tablename__: ClassVar[str] = "ohlcv_data"  # pyright: ignore[reportIncompatibleVariableOverride]

    # Add stock_id and override ts to form a composite primary key
    stock_id: str = Field(primary_key=True)
    # TODO: I think i'll delete this one later.
    trading_date: date = Field(index=True)
    ts: datetime = Field(primary_key=True, description="Timestamp of the candle")

    @model_validator(mode="after")
    def _check_invariants(self) -> "OhlcvDTO":
        assert self.open >= 0, "open must be non-negative"
        assert self.high >= 0, "high must be non-negative"
        assert self.low >= 0, "low must be non-negative"
        assert self.close >= 0, "close must be non-negative"
        assert self.volume >= 0, "volume must be non-negative"
        if self.high > 0 and self.low > 0:
            assert self.high >= self.low, "high must be >= low"
        return self
