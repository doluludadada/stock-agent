# backend/src/c_infrastructure/database/models/watchlist_dto.py

from datetime import datetime
from typing import ClassVar

from sqlmodel import Field

from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.types.enums import WatchlistType


class WatchlistDTO(StockWatchlist, table=True):
    """Database representation of a Watchlist membership."""

    __tablename__: ClassVar[str] = "watchlists"

    # One active membership record per stock.
    stock_id: str = Field(index=True, unique=True)

    type: WatchlistType = Field(index=True)

    expires_at: datetime | None = Field(default=None, index=True)
