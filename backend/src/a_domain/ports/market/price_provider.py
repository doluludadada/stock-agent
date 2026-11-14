from datetime import date, datetime
from typing import Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.rules.trading.ranking import ListedHistory
from a_domain.types.enums import MarketIndex


class IPriceHistoryProvider(Protocol):
    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        """Daily bars per stock, oldest first, each stamped at its session's 13:30 close in Asia/Taipei."""
        ...

    async def fetch_index_history(self, index: MarketIndex, start_date: datetime, end_date: datetime) -> list[Ohlcv]:
        """The index's daily bars, oldest first, stamped like a stock's. Empty when the source has none."""
        ...

    async def listed_history(self) -> ListedHistory | None:
        """
        Every stock's daily bars the source holds, delisted stocks too, as its exchange listed them, neither adjusted nor
        given a change the exchange did not list, with the ex-right references the source holds (ListedHistory); None
        while it holds no bar. It fetches nothing.
        """
        ...

    async def listed_fingerprint(self) -> tuple[object, ...]:
        """
        What tells whether the bars of listed_history and the ex-right references are the ones a reader built from:
        it differs after a bar or a reference is saved, replaced or given its change, by this process or another, so
        what was built from the source is as the source holds it for as long as this stays the same. It may differ
        after a save that changed nothing. It costs the same however many bars the source holds, and fetches nothing.
        """
        ...

    async def ex_right_references(self, first: date, last: date) -> dict[str, dict[datetime, float]]:
        """
        Its exchange's reference price of each stock on each of its ex-right or ex-dividend days from first to last that the
        source holds, by stock id and the stamp of that session's bars: the price a bar of that session compares its close
        to where the exchange gave it no change. fetch_history adjusts across those sessions with them.
        """
        ...

    async def held_span(self) -> tuple[date, date] | None:
        """
        The first and the last session the source already holds stocks' daily bars of, or None when it holds none. It
        asks nothing of the exchanges: a read of that span fetches no older session.
        """
        ...


class IRealtimeQuoteProvider(Protocol):
    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        """Each stock's session so far, closing at its last trade and stamped with that trade's time. No trade, no bar."""
        ...


class IOhlcvProvider(IPriceHistoryProvider, IRealtimeQuoteProvider, Protocol):
    """Daily history for analysis and realtime quotes for orders: what the workflows read."""
