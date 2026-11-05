from collections.abc import Awaitable, Callable
from datetime import date, datetime, tzinfo
from typing import Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.ports.market.price_provider import IOhlcvProvider

type HistoryDownload = Callable[[list[str]], Awaitable[dict[str, list[Ohlcv]]]]
"""Asks the history source for the bars of the keys it is given."""


class ICachedPriceProvider(IOhlcvProvider, Protocol):
    """
    Daily history from a history source, cached in the database, and realtime quotes passed through uncached.

    The cache holds settled sessions only, and a stock whose cached history lacks the last settled session is asked
    for again at most once per retry interval. An index's history is cached the same way, under a key of its own.
    """

    async def cached_history(
        self, stock_ids: list[str], start_date: datetime, end_date: datetime, download: HistoryDownload
    ) -> dict[str, list[Ohlcv]]:
        """The cached bars per key, after `download` fetched those of the keys the cache is behind or short of."""
        ...

    async def download_once(
        self, stock_ids: list[str], first_session: date, last_session: date, download: HistoryDownload
    ) -> dict[str, list[Ohlcv]]:
        """
        What the history source returns for `stock_ids` from first_session to last_session. A stock that another call is
        downloading over the same sessions comes from that download, and `download` runs once for the rest, so loads of
        one stock at once ask the source once while loads of different stocks still run side by side.
        """
        ...

    def stocks_behind(self, stock_ids: list[str], cached: dict[str, list[Ohlcv]], last_settled_session: date) -> list[str]:
        """The stocks whose cached history lacks the last settled session."""
        ...

    def stocks_short_of(
        self, stock_ids: list[str], cached: dict[str, list[Ohlcv]], asked_from: dict[str, date], first_session: date
    ) -> list[str]:
        """
        The cached stocks never asked for from as early as `first_session` (`asked_from`, else their first cached bar,
        with the configured slack for holidays): a strategy that needs more history than earlier runs cached gets it at
        once instead of failing on too few bars. A stock with a short history is asked once per earlier window.
        """
        ...

    async def load_windows(self, stock_ids: list[str]) -> dict[str, date]:
        """The earliest session the history source was asked for, per stock that was ever asked."""
        ...

    async def save_windows(self, stock_ids: list[str], first_session: date, asked_from: dict[str, date]) -> None:
        """Records `first_session` for each stock it is earlier for than `asked_from` holds."""
        ...

    async def stocks_due(self, behind: list[str], last_settled_session: date, now: datetime) -> list[str]:
        """The stocks behind the last settled session that the history source may be asked for now."""
        ...

    async def load_cached_bars(
        self, stock_ids: list[str], start_day: date, end_day: date, zone: tzinfo | None
    ) -> dict[str, list[Ohlcv]]:
        """Cached daily bars per stock from start_day to end_day in `zone`, oldest first."""
        ...

    async def save_bars(self, bars_by_stock: dict[str, list[Ohlcv]]) -> None: ...

    async def save_fetches(self, stock_ids: list[str], fetched_at: datetime, settled_session: date) -> None:
        """Records that the history source was asked for these stocks at fetched_at, when settled_session was the last settled one."""
        ...

    def settled_bars(self, bars_by_stock: dict[str, list[Ohlcv]], last_settled_session: date) -> dict[str, list[Ohlcv]]:
        """Only the bars of sessions up to last_settled_session; a stock left with none is dropped."""
        ...
