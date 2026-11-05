from typing import Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock


class IStockProvider(Protocol):
    """
    Provides the full list of tradable stocks for screening.

    Every call returns new Stock objects holding only identity (stock_id, name, market).
    Workflows fill those objects with prices, articles and reports, so nothing one workflow
    writes may reach the Stock objects that a later call returns.

    It is separate from IOhlcvProvider because a market's stock list and its prices can come from different
    sources: for the US market, the S&P 500 components from one API and their daily bars from another.
    """

    async def get_all(self) -> list[Stock]: ...

    async def get_by_id(self, stock_id: str) -> Stock | None: ...

    async def get_latest_closes(self) -> dict[str, Ohlcv]:
        """
        Each stock's latest official daily close, keyed by stock_id, from the same exchange listing as get_all().
        The bar's ts is its session date at the close. A stock that did not trade in that session is absent.
        """
        ...
