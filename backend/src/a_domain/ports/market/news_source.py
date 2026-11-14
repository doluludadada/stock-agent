from typing import Protocol

from a_domain.model.market.article import Article


class INewsSource(Protocol):
    """One news site: its listing of a stock's recent articles, and each article's page."""

    async def fetch_news(self, stock_id: str, limit: int) -> list[Article]:
        """The stock's newest articles on this site, at most limit, each with its body text where the site gives one."""
        ...
