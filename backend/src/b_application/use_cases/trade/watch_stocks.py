# backend/src/b_application/use_cases/trade/watch_stocks.py

from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import WatchlistType


class WatchStocks:
    """Adds stocks to the watchlist with an explicit source."""

    def __init__(
        self,
        watchlist_repository: IWatchlistRepository,
        logger: ILoggingProvider,
    ) -> None:
        self._watchlist_repository = watchlist_repository
        self._logger = logger

    async def execute(
        self,
        stocks: list[Stock],
        watchlist_type: WatchlistType,
    ) -> StockWatchlist:
        if not stocks:
            self._logger.info(f"Watchlist update skipped. Type={watchlist_type.value}, stocks=0.")
            return StockWatchlist()

        self._logger.info(f"Adding {len(stocks)} stocks to {watchlist_type.value} watchlist.")

        watchlist = await self._watchlist_repository.add(
            stocks=stocks,
            watchlist_type=watchlist_type,
        )

        self._logger.info(f"Watchlist updated. Type={watchlist_type.value}, stocks={len(watchlist.willing_stocks)}.")

        return watchlist
