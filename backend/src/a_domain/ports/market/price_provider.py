from collections.abc import Collection
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


class IQuoteBoard(Protocol):
    """
    The realtime quotes the pages show, held once for every page and user of a runtime, so the number of requests the
    quote source gets does not grow with the tabs that are open. It prices no order: an order's quote is asked of the
    source itself (IRealtimeQuoteProvider), never read here.
    """

    async def follow(self, stock_ids: Collection[str], indexes: Collection[MarketIndex]) -> None:
        """
        Notes that a page asks for these stocks and indexes now, and asks the source once for the ones pages asked for
        lately when the last request of their kind is old enough: the stocks in one request and the indexes in another,
        each paced on its own and neither waiting for the other. A request that fails keeps the quotes held and costs
        the other kind nothing. Of more stocks than one request of the source reads, the first ones are followed.
        """
        ...

    def quotes(self, stock_ids: Collection[str], session: date) -> dict[str, Ohlcv]:
        """
        The quote held of each of these stocks whose last trade was in `session`, as IRealtimeQuoteProvider answered
        it. A stock without one is left out. It asks the source nothing.
        """
        ...

    def index_quotes(self, indexes: Collection[MarketIndex], session: date) -> dict[MarketIndex, Ohlcv]:
        """The quote held of each of these indexes whose latest value is of `session`. It asks the source nothing."""
        ...

    def read_at(self, stock_ids: Collection[str], indexes: Collection[MarketIndex]) -> datetime | None:
        """
        When the source last answered the board's request of the kind named: of the stocks when a stock is named, of
        the indexes when an index is, the earlier of the two when both are; None until each was answered. A request
        that failed does not count, and one kind's answer never counts for the other.
        """
        ...
