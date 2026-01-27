from typing import Protocol

from src.a_domain.model.analysis.analysis_context import AnalysisContext


class IKnowledgeRepository(Protocol):
    """
    Handles both searching (RAG) and saving new knowledge (Ingestion).
    """

    async def search(self, query: str, limit: int = 3) -> str:
        """Retrieves context for Chatbot."""
        ...

    async def save_analysis(self, context: AnalysisContext) -> None:
        """
        Saves the result of the Stock Agent's analysis into the Brain.
        This makes the AI 'remember' why it liked/disliked a stock.
        """
        ...
