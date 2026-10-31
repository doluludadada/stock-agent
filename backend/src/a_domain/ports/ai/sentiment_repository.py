from typing import Protocol

from a_domain.model.analysis.sentiment_classification import SentimentClassification


class ISentimentRepository(Protocol):
    """Social posts already classified, by the post's URL, so the same public post is never classified twice."""

    async def find_classifications(self, stock_id: str, urls: list[str]) -> dict[str, SentimentClassification]:
        """The saved classification of each of these posts about the stock, by URL. A post never classified is left out."""
        ...

    async def save_classifications(self, stock_id: str, classifications: dict[str, SentimentClassification]) -> None:
        """Inserts or replaces each post's classification by (stock_id, URL)."""
        ...
