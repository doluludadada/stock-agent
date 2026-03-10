from typing import Protocol

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

    async def get_by_id(self, stock_id: str) -> Stock | None: ...