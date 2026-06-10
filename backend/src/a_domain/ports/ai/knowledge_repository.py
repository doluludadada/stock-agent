from typing import Protocol

from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal


class IKnowledgeRepository(Protocol):
    """Stores and retrieves historical trading decisions for RAG."""

    async def search(
        self,
        query: str,
        limit: int = 3,
    ) -> str: ...

    async def save_decision(
        self,
        stock: Stock,
        signal: TradeSignal,
    ) -> None: ...