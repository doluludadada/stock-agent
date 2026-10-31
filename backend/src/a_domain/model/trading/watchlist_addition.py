from dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.trading.stock_watchlist import StockWatchlist
from a_domain.model.trading.watchlist_entry import WatchlistEntry
from a_domain.types.enums import WatchlistType


@dataclass(frozen=True)
class WatchlistAddition:
    """Outcome of adding stocks to one watchlist type."""

    watchlist_type: WatchlistType
    stocks: list[Stock]
    already_present_stock_ids: list[str]
    entries: list[WatchlistEntry]
    """Entries to persist: new memberships plus renewed automatic ones."""

    @property
    def added_stock_ids(self) -> list[str]:
        return [stock.stock_id for stock in self.stocks if stock.stock_id not in self.already_present_stock_ids]

    @property
    def watchlist(self) -> StockWatchlist:
        return StockWatchlist(willing_stocks=list(self.stocks))
