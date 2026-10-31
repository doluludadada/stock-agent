from datetime import date
from typing import Any, Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.types.enums import MarketType


class ITaiwanStockProvider(IStockProvider, Protocol):
    """The TWSE and TPEX daily-quotes listings: every listed and OTC stock and its latest official close."""

    async def cached_stocks(self) -> list[Stock]:
        """The listed stocks, fetched again once the cached listings are older than the cache lifetime."""
        ...

    async def fetch_listings(self) -> tuple[list[Stock], dict[str, Ohlcv]]:
        """Both listings' stocks and their closes. A failed fetch is logged and yields neither."""
        ...

    def parse_listing(self, rows: list[dict[str, Any]], market: MarketType) -> tuple[list[Stock], dict[str, Ohlcv]]:
        """The stocks with a four-digit code in one exchange's listing, and the official close of each that traded."""
        ...

    def parse_roc_date(self, text: str) -> date:
        """'1151029' (ROC year 115) is 2026-10-29."""
        ...

    def parse_daily_close(self, row: dict[str, Any], fields: tuple[str, str, str, str, str, str]) -> Ohlcv | None:
        """The row's official daily bar, or None when the stock did not trade (TWSE leaves prices blank, TPEX writes '---')."""
        ...
