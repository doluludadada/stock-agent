# backend/src/a_domain/model/trading/watchlist.py

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from a_domain.model.market.stock import Stock


@dataclass
class StockWatchlist:
    """Runtime view of stocks currently tracked by the system."""

    watchlist_id: UUID = field(default_factory=uuid4)
    willing_stocks: list[Stock] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
