from datetime import datetime

from pydantic.dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist import WatchlistEntry
from a_domain.types.enums import WatchlistType


@dataclass(frozen=True)
class WatchlistAddition:
    """What WatchlistRule decided for one watchlist type: the entries to save, and the stocks that were already on it."""

    watchlist_type: WatchlistType
    entries: list[WatchlistEntry]
    """Entries to persist: new memberships plus renewed automatic ones."""

    already_present_stock_ids: list[str]

    @property
    def added_stock_ids(self) -> list[str]:
        return [entry.stock_id for entry in self.entries if entry.stock_id not in self.already_present_stock_ids]


@dataclass(frozen=True)
class WatchlistRule:
    """
    Decides how stocks join the watchlist.

    A stock holds one entry per watchlist type, so it may be TECHNICAL, BUZZ and MANUAL at once.
    MANUAL outranks the automatic types: a MANUAL entry never expires and no automatic workflow changes it,
    so a manually watched stock stays on the watchlist after its TECHNICAL or BUZZ entry lapses.
    An automatic entry expires at `automatic_expires_at` and is renewed whenever its workflow selects the stock again.
    """

    def apply(
        self,
        active_entries: list[WatchlistEntry],
        stocks: list[Stock],
        watchlist_type: WatchlistType,
        now: datetime,
        automatic_expires_at: datetime,
    ) -> WatchlistAddition:
        current_entries = {entry.stock_id: entry for entry in active_entries if entry.watchlist_type == watchlist_type}
        unique_stocks = list({stock.stock_id: stock for stock in stocks}.values())
        already_present_stock_ids = [stock.stock_id for stock in unique_stocks if stock.stock_id in current_entries]
        is_manual = watchlist_type == WatchlistType.MANUAL

        entries = [
            WatchlistEntry(
                stock_id=stock.stock_id,
                watchlist_type=watchlist_type,
                created_at=current_entries[stock.stock_id].created_at if stock.stock_id in current_entries else now,
                expires_at=None if is_manual else automatic_expires_at,
            )
            for stock in unique_stocks
            if not (is_manual and stock.stock_id in current_entries)
        ]

        return WatchlistAddition(watchlist_type=watchlist_type, entries=entries, already_present_stock_ids=already_present_stock_ids)
