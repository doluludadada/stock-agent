from dataclasses import dataclass


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    content: str


