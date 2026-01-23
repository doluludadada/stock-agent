from typing import Protocol

from src.a_domain.model.analysis.web_search_result import WebSearchResult


class IWebSearchPort(Protocol):
    async def search(self, query: str, limit: int = 3) -> list[WebSearchResult]: ...
