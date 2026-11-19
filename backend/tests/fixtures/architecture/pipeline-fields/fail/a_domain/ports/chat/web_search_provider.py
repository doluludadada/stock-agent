from typing import Protocol

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str


class IWebSearchProvider(Protocol):
    async def search(self, query: str) -> list[WebSearchResult]: ...
