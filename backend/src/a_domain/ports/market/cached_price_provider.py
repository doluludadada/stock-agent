from collections.abc import Mapping
from datetime import date, datetime
from typing import Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.types.enums import MarketType


class ICachedPriceProvider(IOhlcvProvider, Protocol):
    """
    A personal site's daily history from its broker, kept in the database, and the broker's realtime quotes passed
    through uncached.

    The broker serves every listed stock's daily bar of one session per request, without the change from the
    session's reference price, and each exchange's own index from its one-minute bars. The cache holds settled sessions
    only: the index sessions it lacks first, then the stocks of every index session it holds no stock of, newest first.
    The last settled session's bars that hold no change get each stock's change from the broker's snapshots, which show
    that session until the next one opens; a bar of an older session reads the open-data archive's official change of
    its stock and session where the broker gave none. A read adjusts each stock's bars for the corporate actions those
    changes show (HistoryAdjustmentRule), against the index sessions that hold the stocks, and warns how many of its
    sessions hold a bar with no change, which no factor crosses. The broker is asked the same question at most once per
    market_data.history_retry_hours, answered or failed, so a session it does not serve yet, an index range without a
    new session, or a broker whose login is down is not asked at every read. An index's bars are kept under `^` and its
    market, which no stock id can be.
    """

    def sessions_of(self, start_date: datetime, end_date: datetime) -> tuple[date, date]:
        """The window's first session and its last, which is never after the last settled session."""
        ...

    async def sync(self, start_date: datetime, end_date: datetime) -> tuple[date, date]:
        """
        Fetches what the cache lacks of the window's sessions, up to the last settled session, and returns the window's
        first and last session.
        """
        ...

    async def sync_index(self, market: MarketType, first: date, last: date) -> None:
        """
        Fetches the market's index sessions the cache lacks from first to last: after the latest it holds, and before the
        earliest when that is more than market_data.history_start_slack_days after first, since holidays leave days
        without a session.
        """
        ...

    async def index_gaps(self, market: MarketType, first: date, last: date) -> list[tuple[date, date]]:
        """The ranges of the market's index sessions from first to last that sync_index asks the broker for."""
        ...

    async def sync_session(self, session: date) -> bool:
        """
        Fetches and saves one session's bars unless the cache holds it or the broker was asked for it within the retry
        interval. Returns whether it saved any.
        """
        ...

    async def sync_changes(self, session: date) -> None:
        """
        Gives each stock's bar of the session that holds no change its change from the broker's snapshots, unless they
        were asked within the retry interval. The caller asks only while the snapshots still show the session: it is the
        last settled session.
        """
        ...

    def due(self, question: str, now: datetime) -> bool:
        """Whether the broker may be asked `question` now: it never was, or was a retry interval ago."""
        ...

    async def held_sessions(self, first: date, last: date) -> set[date]:
        """The sessions from first to last the cache holds stocks' bars of."""
        ...

    async def index_sessions(self, first: date, last: date) -> dict[MarketType, list[Ohlcv]]:
        """Each market's index bars from first to last, oldest first."""
        ...

    async def stored_bars(self, stock_ids: list[str], first: date, last: date) -> dict[str, list[Ohlcv]]:
        """
        Each stock's bars from first to last as the broker served them, oldest first, a bar without a change with the
        open-data archive's official change of its stock and session where the archive holds one.
        """
        ...

    async def save_bars(self, bars: Mapping[str, list[Ohlcv]]) -> None:
        """Saves each key's bars, replacing what the cache holds of the same key and session."""
        ...
