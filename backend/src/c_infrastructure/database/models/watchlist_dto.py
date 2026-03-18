# backend/src/c_infrastructure/database/models/watchlist_dto.py
from datetime import datetime
from typing import ClassVar
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class WatchlistDTO(SQLModel, table=True):
    """Infrastructure Database Model for tracking Watchlists."""

    __tablename__: ClassVar[str] = "watchlists"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    stock_id: str = Field(index=True)
    list_type: str = Field(index=True)  # "TECHNICAL" or "BUZZ"
    reason: str
    created_at: datetime = Field(default_factory=datetime.now)
