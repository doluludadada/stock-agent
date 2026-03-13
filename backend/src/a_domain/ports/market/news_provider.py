from typing import Protocol

from a_domain.model.market.article import Article


class INewsProvider(Protocol):
    async def fetch_news(self, stock_id: str, limit: int = 10) -> list[Article]:
        """
        fetch news from internet.
        """
        ...

    def save_as_md_file(self, stock_id: str, articles: list[Article]) -> None:
        """Saves fetched articles as a Markdown file for human auditing."""
        ...
