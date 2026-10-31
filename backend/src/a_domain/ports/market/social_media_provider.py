from collections.abc import Mapping
from datetime import date
from typing import Protocol

from a_domain.model.market.article import Article
from a_domain.model.market.post_listing import PostListing


class ISocialMediaProvider(Protocol):
    """Provides recent social-market discussions: the posts of a stock board, read through its tag search."""

    async def fetch_social_articles(self, limit: int) -> list[Article]:
        """Recent posts under each configured tag that name a listed stock, at most limit, once per post."""
        ...

    def save_social_media_data(self, articles: list[Article]) -> None:
        """Saves fetched social articles as a Markdown file."""
        ...

    async def fetch_tag_articles(self, tag: str, stock_ids: set[str], since: date, limit: int) -> list[Article]:
        """The posts under one tag, page by page back to `since`, that name one of stock_ids, at most limit."""
        ...

    async def fetch_page(self, url: str, params: Mapping[str, str] | None = None) -> str | None:
        """The text of a board page, or None when the board could not be read."""
        ...

    def parse_listings(self, page: str) -> list[PostListing]:
        """The posts a search page lists, in its order."""
        ...

    def previous_page_url(self, page: str) -> str | None:
        """The search page with the older posts, or None on the last page."""
        ...

    def parse_article(self, page: str, listing: PostListing, stock_ids: set[str]) -> Article | None:
        """The post on its page, or None when it names no stock in stock_ids or has no text."""
        ...

    def to_article(self, stock_id: str, listing: PostListing, reactions: list[str], text: str) -> Article | None:
        """The post as an article, its cleaned text headed by its reaction counts, or None when no text is left."""
        ...

    def extract_stock_id(self, body: str, title: str) -> str | None:
        """The stock a post is about: its ticker line, else a parenthesized id, else an id in its title."""
        ...

    def clean_content(self, text: str) -> str:
        """The post's text without the board's signature, reminder and blank lines."""
        ...
