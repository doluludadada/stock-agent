from datetime import datetime

from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist_addition import WatchlistAddition
from a_domain.model.trading.watchlist_entry import WatchlistEntry
from a_domain.types.enums import WatchlistType


class WatchlistRule:
    """
    Decides how stocks join the watchlist.

    A stock holds one entry per watchlist type, so it may be TECHNICAL, BUZZ and MANUAL at once.
    MANUAL outranks the automatic types: a MANUAL entry never expires and no automatic workflow changes it,
    so a manually watched stock stays on the watchlist after its TECHNICAL or BUZZ entry lapses.
    An automatic entry expires at `automatic_expires_at` and is renewed whenever its workflow selects the stock again.
    """

    @staticmethod
    def add(
        active_entries: list[WatchlistEntry],
        stocks: list[Stock],
        watchlist_type: WatchlistType,
        now: datetime,
        automatic_expires_at: datetime,
    ) -> WatchlistAddition:
        current_entries = {entry.stock_id: entry for entry in active_entries if entry.watchlist_type == watchlist_type}
        unique_stocks = list({stock.stock_id: stock for stock in stocks}.values())
        already_present_stock_ids: list[str] = []
        entries: list[WatchlistEntry] = []

        for stock in unique_stocks:
            current_entry = current_entries.get(stock.stock_id)

            if current_entry is not None:
                already_present_stock_ids.append(stock.stock_id)

            if current_entry is not None and watchlist_type == WatchlistType.MANUAL:
                continue

            entries.append(
                WatchlistEntry(
                    stock_id=stock.stock_id,
                    watchlist_type=watchlist_type,
                    created_at=current_entry.created_at if current_entry is not None else now,
                    expires_at=None if watchlist_type == WatchlistType.MANUAL else automatic_expires_at,
                )
            )

        return WatchlistAddition(
            watchlist_type=watchlist_type, stocks=unique_stocks, already_present_stock_ids=already_present_stock_ids, entries=entries
        )
