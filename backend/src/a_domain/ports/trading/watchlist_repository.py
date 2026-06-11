from typing import Protocol

from a_domain.model.trading.watchlist import StockWatchlist


class IWatchlistRepository(Protocol):
    async def get_active(self) -> StockWatchlist: ...

    async def upsert(
        self,
        entries: StockWatchlist,
    ) -> None: ...

    async def remove(
        self,
        stock_id: str,
    ) -> None: ...
