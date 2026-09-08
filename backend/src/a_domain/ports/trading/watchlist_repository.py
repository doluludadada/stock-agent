# backend/src/a_domain/ports/trading/watchlist_repository.py

from typing import Protocol

from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.types.enums import WatchlistType


class IWatchlistRepository(Protocol):
    async def get_active(self) -> StockWatchlist: ...

    async def add(self, stocks: list[Stock], watchlist_type: WatchlistType) -> StockWatchlist: ...

    async def remove(self, stock_id: str) -> None: ...
