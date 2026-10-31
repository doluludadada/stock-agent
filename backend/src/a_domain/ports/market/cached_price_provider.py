from datetime import date, datetime, tzinfo
from typing import Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IOhlcvProvider


class ICachedPriceProvider(IOhlcvProvider, Protocol):
    """
    Daily history from a history source, cached in the database, and realtime quotes passed through uncached.

    The cache holds settled sessions only, and a stock whose cached history lacks the last settled session is asked
    for again at most once per retry interval.
    """

    def stocks_behind(self, stocks: list[Stock], cached: dict[str, list[Ohlcv]], last_settled_session: date) -> list[Stock]:
        """The stocks whose cached history lacks the last settled session."""
        ...

    async def stocks_due(self, behind: list[Stock], last_settled_session: date, now: datetime) -> list[Stock]:
        """The stocks behind the last settled session that the history source may be asked for now."""
        ...

    async def load_cached_bars(
        self, stock_ids: list[str], start_day: date, end_day: date, zone: tzinfo | None
    ) -> dict[str, list[Ohlcv]]:
        """Cached daily bars per stock from start_day to end_day in `zone`, oldest first."""
        ...

    async def save_bars(self, bars_by_stock: dict[str, list[Ohlcv]]) -> None: ...

    async def save_fetches(self, stocks: list[Stock], fetched_at: datetime, settled_session: date) -> None:
        """Records that the history source was asked for these stocks at fetched_at, when settled_session was the last settled one."""
        ...

    def settled_bars(self, bars_by_stock: dict[str, list[Ohlcv]], last_settled_session: date) -> dict[str, list[Ohlcv]]:
        """Only the bars of sessions up to last_settled_session; a stock left with none is dropped."""
        ...
