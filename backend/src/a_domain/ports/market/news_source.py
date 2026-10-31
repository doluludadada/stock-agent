from collections.abc import Mapping
from typing import Protocol

from a_domain.model.market.article import Article


class INewsSource(Protocol):
    """One news site: its listing of a stock's recent articles, and each article's page."""

    async def fetch_news(self, stock_id: str, limit: int) -> list[Article]:
        """The stock's newest articles on this site, at most limit, each with its body text where the site gives one."""
        ...

    async def fetch_page(self, url: str, params: Mapping[str, str | int] | None = None) -> str | None:
        """The text of a listing page or feed, or None when the site refused or could not be reached."""
        ...

    def parse_listing(self, stock_id: str, page: str) -> list[Article]:
        """The articles a listing page or feed names, in its order, with the text the listing itself carries."""
        ...

    async def fetch_article_body(self, url: str) -> str:
        """The text of an article page, or an empty string when the page cannot be read."""
        ...
