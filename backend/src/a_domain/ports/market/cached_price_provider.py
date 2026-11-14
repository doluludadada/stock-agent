from datetime import date, datetime
from typing import Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.types.enums import MarketType


class ICachedPriceProvider(IOhlcvProvider, Protocol):
    """
    A personal site's daily history from the exchanges' own daily reports (IDailyHistorySource), kept in the database,
    and its realtime quotes passed through uncached: the broker's on a Shioaji login, else the open-data archive's
    refusal of every quote.

    The reports serve every listed stock's daily bar of one session per exchange and request, with its official change
    from the session's reference price, each exchange's own index per month, and each exchange's ex-right references of
    a range of dates. The cache holds settled sessions only: the index sessions it lacks first, then the ex-right
    references of the days it never read, then the stocks of every index session it holds no stock bar of, newest first. A
    session whose bars hold no change at all, as Shioaji's daily quotes saved them before, is asked again when the Web
    API's timer syncs, and the report gives each bar its change. A bar that still holds none, where the exchange
    compared its close to no reference, reads the open-data archive's official change of its stock and session where the
    archive holds one. A read adjusts each stock's bars for the corporate actions those changes and the ex-right
    references show (HistoryAdjustmentRule), against the index sessions that hold the stocks, and warns how many of its
    sessions hold a bar with neither, which no factor crosses. The exchanges are asked the same question at most once per
    market_data.history_retry_hours, answered or failed, and nothing within it after any request failed, so a session
    they do not serve yet, an index range without a new session, or a site that refuses the address is not asked at
    every read. An index's bars are kept under `^` and its market, which no stock id can be.
    """

    async def sync(self, start_date: datetime, end_date: datetime, *, reported: bool = False) -> tuple[date, date]:
        """
        Fetches what the cache lacks of the window's sessions, up to the last settled session, and returns the window's
        first and last session. `reported` fetches again, too, every session the cache holds without any change, so a
        read never waits for those: the Web API's timer asks for it.
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
        """The ranges of the market's index sessions from first to last that sync_index asks the exchange for."""
        ...

    async def sync_references(self, first: date, last: date) -> None:
        """
        Fetches each exchange's ex-right references of the ranges reference_gaps names, a range at a time, each saved
        with the days it covers as it comes. A request that fails ends it, and like any failure stops every request to
        the exchanges for the retry interval; the ranges not read stay gaps, which the next sync asks for.
        """
        ...

    async def reference_gaps(self, market: MarketType, first: date, last: date) -> list[tuple[date, date]]:
        """
        The ranges from first to last whose ex-right references the cache never read from the exchange, in the order
        sync_references asks for them, each cut at the boundaries of
        sources.exchange.ex_right_references.months_per_request calendar months: those before the days it read newest
        first, then those after them oldest first, so the days read stay one span whichever request fails. A range read
        and found without an ex-day is no gap.
        """
        ...

    async def sync_session(self, session: date) -> bool:
        """
        Fetches and saves one session's bars unless the cache holds its reported bars or the exchanges were asked for it
        within the retry interval. Returns whether it saved any.
        """
        ...

    async def held_sessions(self, first: date, last: date, *, reported: bool = False) -> set[date]:
        """
        The sessions from first to last the cache holds stocks' bars of; `reported`, only those where some stock's bar
        holds its change, as every session of the exchanges' reports does.
        """
        ...

    async def index_sessions(self, first: date, last: date) -> dict[MarketType, list[Ohlcv]]:
        """Each market's index bars from first to last, oldest first."""
        ...
