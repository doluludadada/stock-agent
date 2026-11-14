from typing import Protocol

from a_domain.model.market.article import Article


class IStockFeed(Protocol):
    """
    What the news sites and the stock board say about one stock, for its page, on a site whose audience may read them
    (Audience.news_articles). A page view must not reach those sites each time, so what was fetched for a stock is held
    and served again for a freshness window, and one fetch runs per stock at a time. A site that fails or answers
    nothing leaves what was held of it in place, so the page degrades to the last articles fetched, never to an error.
    """

    async def fetch(self, stock_id: str, limit: int) -> list[Article]:
        """The stock's news articles and board posts, at most limit of each, as last fetched within the freshness window."""
        ...
