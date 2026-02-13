from typing import Protocol

from backend.src.a_domain.model.market.stock import Stock


class IStockProvider(Protocol):
    """Provides the full list of tradable stocks for screening."""

    async def get_all(self) -> list[Stock]: ...
