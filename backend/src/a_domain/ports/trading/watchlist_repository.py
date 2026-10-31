from typing import Protocol

from a_domain.model.trading.watchlist_entry import WatchlistEntry


class IWatchlistRepository(Protocol):
    async def get_active(self) -> list[WatchlistEntry]:
        """Returns entries that never expire or have not expired yet."""
        ...

    async def save(self, entries: list[WatchlistEntry]) -> None:
        """Inserts or replaces each entry by (stock_id, watchlist_type)."""
        ...
