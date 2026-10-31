from typing import Any, Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IPriceHistoryProvider


class IYahooPriceHistoryProvider(IPriceHistoryProvider, Protocol):
    """Daily history from Yahoo Finance, downloaded in batches of tickers."""

    async def download_bars(self, stocks: list[Stock], start: str, end: str) -> dict[str, list[Ohlcv]]:
        """Daily bars per stock from start (inclusive) to end (exclusive), both YYYY-MM-DD, one batch after another."""
        ...

    async def download_batch(self, stocks: list[Stock], start: str, end: str) -> dict[str, list[Ohlcv]]:
        """One download of these stocks' daily bars. A stock Yahoo has no bars for is absent."""
        ...

    def to_bars(self, download: Any, ticker: str) -> list[Ohlcv]:
        """One ticker's bars in the frame yfinance.download returned, each stamped at its session's close."""
        ...
