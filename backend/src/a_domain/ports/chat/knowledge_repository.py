from typing import Protocol

from backend.src.a_domain.model.market.stock import Stock


class IKnowledgeRepository(Protocol):
    """
    Handles both searching (RAG) and saving new knowledge (Ingestion).
    """

    async def search(self, query: str, limit: int = 3) -> str:
        """Retrieves context for Chatbot."""
        ...

    async def save_analysis(self, context: Stock) -> None:
        """
        Saves the result of the Stock Agent's analysis into the Brain.
        This makes the AI 'remember' why it liked/disliked a stock.
        """
        ...
