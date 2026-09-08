# backend/src/c_infrastructure/database/models/watchlist_dto.py

from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel

from a_domain.types.enums import WatchlistType


class WatchlistDTO(SQLModel, table=True):
    """One persisted watchlist membership source for one stock."""

    __tablename__: ClassVar[str] = "watchlists"

    stock_id: str = Field(primary_key=True)
    type: WatchlistType = Field(sa_column=Column(String, primary_key=True, nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = Field(default=None, index=True)
