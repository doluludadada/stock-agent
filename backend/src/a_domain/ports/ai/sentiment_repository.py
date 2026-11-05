from typing import Protocol

from a_domain.model.market.article import Article


class ISentimentRepository(Protocol):
    """Social posts already classified, by the post's URL, so the same public post is never classified twice."""

    async def find_classified(self, stock_id: str, posts: list[Article]) -> list[Article]:
        """
        A copy of each of these posts about the stock whose URL has a saved sentiment, with that sentiment, in post
        order. A post without a URL or never classified is left out.
        """
        ...

    async def save_classified(self, stock_id: str, posts: list[Article]) -> None:
        """Inserts or replaces each post's sentiment by (stock_id, URL). A post without a URL or a sentiment is skipped."""
        ...
