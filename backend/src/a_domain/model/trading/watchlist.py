from datetime import datetime, timezone

from sqlmodel import Field, SQLModel

from a_domain.types.enums import WatchlistType


class StockWatchlist(SQLModel):
    """
    Persistent candidate membership.

    Market data, technical indicators, AI analysis and scores
    remain on the runtime Stock model.
    """

    stock_id: str
    type: WatchlistType

    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
