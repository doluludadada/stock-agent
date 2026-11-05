from datetime import datetime
from typing import Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.types.enums import MarketIndex


class IPriceHistoryProvider(Protocol):
    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        """Daily bars per stock, oldest first, each stamped at its session's 13:30 close in Asia/Taipei."""
        ...

    async def fetch_index_history(self, index: MarketIndex, start_date: datetime, end_date: datetime) -> list[Ohlcv]:
        """The index's daily bars, oldest first, stamped like a stock's. Empty when the source has none."""
        ...


class IRealtimeQuoteProvider(Protocol):
    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        """Each stock's session so far, closing at its last trade and stamped with that trade's time. No trade, no bar."""
        ...


class IOhlcvProvider(IPriceHistoryProvider, IRealtimeQuoteProvider, Protocol):
    """Daily history for analysis and realtime quotes for orders: what the workflows read."""
