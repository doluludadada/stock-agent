from typing import Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock


class IStockProvider(Protocol):
    """
    Provides the full list of tradable stocks for screening.

    NOTE: This is intentionally kept separate from IPriceProvider.
    This design ensures flexibility for future expansions (e.g., US Market),
    where fetching the list of S&P 500 components might come from one API,
    while fetching historical OHLCV prices comes from another.
    """

    async def get_all(self) -> list[Stock]: ...

    """
    They only contain stock_id (e.g., "2330") and name (e.g., "台積電").
    """

    async def get_by_id(self, stock_id: str) -> Stock | None: ...

    async def get_latest_closes(self) -> dict[str, Ohlcv]:
        """
        Each stock's latest official daily close, keyed by stock_id, from the same exchange listing as get_all().
        The bar's ts is its session date at the close. A stock that did not trade in that session is absent.
        """
        ...
