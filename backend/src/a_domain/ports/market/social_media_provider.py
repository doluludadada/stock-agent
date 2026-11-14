from datetime import date
from typing import Protocol

from a_domain.model.market.article import Article


class ISocialMediaProvider(Protocol):
    """Provides recent social-market discussions: the posts of a stock board, read through its tag search."""

    async def fetch_social_articles(self, limit: int) -> list[Article]:
        """Recent posts under each configured tag that name a listed stock, at most limit, once per post."""
        ...

    async def fetch_stock_posts(self, stock_id: str, limit: int) -> list[Article]:
        """
        The newest posts the board's search lists for the stock's code, at most limit, from one search page: each post's
        title, address and day, with no text, since no post's page is read. Empty when the board could not be read.
        """
        ...

    def save_social_media_data(self, articles: list[Article]) -> None:
        """Saves fetched social articles as a Markdown file."""
        ...

    async def fetch_tag_articles(self, tag: str, stock_ids: set[str], since: date, limit: int) -> list[Article]:
        """The posts under one tag, page by page back to `since`, that name one of stock_ids, at most limit."""
        ...
