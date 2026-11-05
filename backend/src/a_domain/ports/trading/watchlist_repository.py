from typing import Protocol

from a_domain.model.trading.watchlist import WatchlistEntry
from a_domain.types.enums import WatchlistType


class IWatchlistRepository(Protocol):
    async def get_active(self) -> list[WatchlistEntry]:
        """Returns entries that never expire or have not expired yet."""
        ...

    async def save(self, entries: list[WatchlistEntry]) -> None:
        """Inserts or replaces each entry by (stock_id, watchlist_type)."""
        ...

    async def remove(self, stock_ids: list[str], watchlist_type: WatchlistType) -> list[str]:
        """Deletes each stock's entry of that type and returns the stock ids that had one. Other types stay."""
        ...
