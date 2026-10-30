# backend/src/a_domain/ports/trading/watchlist_repository.py

from typing import Protocol

from a_domain.model.trading.watchlist import WatchlistEntry


class IWatchlistRepository(Protocol):
    async def get_active(self) -> list[WatchlistEntry]:
        """Returns entries that never expire or have not expired yet."""
        ...

    async def save(self, entries: list[WatchlistEntry]) -> None:
        """Inserts or replaces each entry by (stock_id, watchlist_type)."""
        ...

    async def remove(self, stock_id: str) -> None: ...
