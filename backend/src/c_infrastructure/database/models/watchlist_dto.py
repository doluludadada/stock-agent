# backend/src/c_infrastructure/database/models/watchlist_dto.py

from datetime import datetime, timezone
from typing import ClassVar

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel

from a_domain.types.enums import WatchlistType


class WatchlistDTO(SQLModel, table=True):
    """Database representation of a Watchlist membership."""

    __tablename__: ClassVar[str] = "watchlists"

    # One active membership record per stock.
    stock_id: str = Field(primary_key=True)

    type: WatchlistType = Field(sa_column=Column(String, index=True, nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = Field(default=None, index=True)
