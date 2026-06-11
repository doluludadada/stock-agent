from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from a_domain.model.market.stock import Stock


@dataclass
class StockWatchlist:
    """
    Runtime watchlist built by the pipeline.

    Contains stocks that passed technical and AI gates and are worth watching
    for possible entry.
    """

    watchlist_id: UUID = field(default_factory=uuid4)
    willing_stocks: list[Stock] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None

    def add(self, stock: Stock) -> None:
        for existing in self.willing_stocks:
            if existing.stock_id == stock.stock_id:
                return

        self.willing_stocks.append(stock)

    def add_many(self, stocks: list[Stock]) -> None:
        for stock in stocks:
            self.add(stock)
