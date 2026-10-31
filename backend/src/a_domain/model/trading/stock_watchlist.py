from dataclasses import dataclass, field
from typing import Self

from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist_entry import WatchlistEntry


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
