from dataclasses import dataclass
from datetime import datetime

from a_domain.types.enums import WatchlistType


@dataclass(frozen=True)
class WatchlistEntry:
    """One stock's membership of one watchlist type. An entry without expires_at never expires."""

    stock_id: str
    watchlist_type: WatchlistType
    created_at: datetime
    expires_at: datetime | None
