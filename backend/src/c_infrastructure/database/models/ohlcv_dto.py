from datetime import datetime
from typing import ClassVar

from sqlmodel import Field

from a_domain.model.market.ohlcv import Ohlcv


class OhlcvDTO(Ohlcv, table=True):
    """Infrastructure Database Model for Caching OHLCV Data."""

    __tablename__: ClassVar[str] = "ohlcv_data"

    # Add stock_id and override ts to form a composite primary key
    stock_id: str = Field(primary_key=True)
    ts: datetime = Field(primary_key=True, description="Timestamp of the candle")
