from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import WatchlistType


class UnwatchStocks:
    """
    Takes stocks off the MANUAL watchlist, the one the user keeps. A stock's TECHNICAL and BUZZ entries stay: their
    workflows added them and they expire on their own.
    """

    def __init__(self, watchlist_repository: IWatchlistRepository, logger: ILoggingProvider) -> None:
        self._watchlist_repository = watchlist_repository
        self._logger = logger

    async def execute(self, stock_ids: list[str]) -> list[str]:
        removed = await self._watchlist_repository.remove(stock_ids, WatchlistType.MANUAL)
        self._logger.info(f"Manual watchlist: removed {len(removed)} of {len(stock_ids)} requested stocks.")

        return removed
