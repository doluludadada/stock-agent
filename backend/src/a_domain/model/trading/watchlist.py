# backend/src/a_domain/model/trading/watchlist.py

from dataclasses import dataclass, field
from datetime import datetime
from typing import Self

from a_domain.model.market.stock import Stock
from a_domain.types.enums import WatchlistType


@dataclass(frozen=True)
class WatchlistEntry:
    """One stock's membership of one watchlist type. An entry without expires_at never expires."""

    stock_id: str
    watchlist_type: WatchlistType
    created_at: datetime
    expires_at: datetime | None


@dataclass
class StockWatchlist:
    """Runtime view of watched stocks, one Stock per stock_id holding every type it is watched under."""

    willing_stocks: list[Stock] = field(default_factory=list)

    @classmethod
    def from_entries(cls, entries: list[WatchlistEntry]) -> Self:
        stocks_by_id: dict[str, Stock] = {}

        for entry in entries:
            stock = stocks_by_id.setdefault(entry.stock_id, Stock(stock_id=entry.stock_id))
            stock.watchlist_types.add(entry.watchlist_type)

        return cls(willing_stocks=list(stocks_by_id.values()))


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
