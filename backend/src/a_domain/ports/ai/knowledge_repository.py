from typing import Protocol

from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal


class IKnowledgeRepository(Protocol):
    """Handles both searching (RAG) and saving new knowledge (Ingestion)."""

    async def search(self, query: str, limit: int = 3) -> str:
        """Retrieves context for Chatbot or Pipeline."""
        ...

    async def save_analysis(self, context: Stock) -> None:
        """Saves analysis result into the knowledge base (RAG memory)."""
        ...

    async def save_decision(self, stock: Stock, signal: TradeSignal) -> None:
        """Saves final BUY / SELL / HOLD decision summary into the knowledge base."""
        ...
