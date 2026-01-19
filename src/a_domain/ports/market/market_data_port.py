from typing import Protocol
from datetime import datetime
from src.a_domain.model.market.stock import Stock
from src.a_domain.model.market.ohlcv import Ohlcv
from src.a_domain.model.market.news import News


class MarketDataPort(Protocol):
    """
    Interface for retrieving raw market data (Price, Volume, News).
    This abstracts away APIs like Shioaji, Yahoo Finance, or Crawl4AI.
    """

    async def get_all_stocks(self) -> list[Stock]:
        """
        Get list of all available stocks targets.
        """
        ...

    async def get_price_history(
        self, symbol: str, start_date: datetime, end_date: datetime
    ) -> list[Ohlcv]:
        """
        Get historical K-bars (OHLCV).
        Using simple list instead of Sequence for ease of use.
        """
        ...

    async def get_latest_news(self, symbol: str, days: int = 3) -> list[News]:
        """
        Get recent news for a specific stock to feed the AI.
        """
        ...
