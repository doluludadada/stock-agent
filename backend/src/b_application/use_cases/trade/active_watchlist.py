from a_domain.model.trading.watchlist import WatchlistEntry
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository


class ActiveWatchlist:
    """The watchlist page: every entry that never expires or has not expired yet, one per stock and watchlist type."""

    def __init__(self, watchlist_repository: IWatchlistRepository) -> None:
        self._watchlist_repository = watchlist_repository

    async def execute(self) -> list[WatchlistEntry]:
        return await self._watchlist_repository.get_active()
