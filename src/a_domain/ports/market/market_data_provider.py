from datetime import datetime
from typing import Protocol

from src.a_domain.model.market.ohlcv import Ohlcv


class IMarketDataProvider(Protocol):
    """
    Interface for Market Data (Broker API / Data Feed).
    Distinguishes between 'Live' data (Intraday) and 'Static' data (Historical).
    """

    async def fetch_realtime_bars(self, stock_ids: list[str]) -> dict[str, Ohlcv]:
        """
        Fetches the latest intraday OHLCV bar for a batch of stocks.
        Returns: A dict mapping stock_id to the current incomplete K-bar.
        """
        ...

    async def fetch_history(self, stock_id: str, start_date: datetime, end_date: datetime) -> list[Ohlcv]:
        """
        Fetches historical K-bars for indicator calculation.
        """
        ...
