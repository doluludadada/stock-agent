from typing import Protocol

from a_domain.model.chat.web_search_result import WebSearchResult


class IWebSearchProvider(Protocol):
    async def search(self, query: str, limit: int = 3) -> list[WebSearchResult]: ...


