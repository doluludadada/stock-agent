from typing import Protocol

from a_domain.model.analysis.sentiment_classification import SentimentClassification
from a_domain.model.market.article import Article


class ISentimentClassifier(Protocol):
    """Classifies social posts, so the model behind it can be replaced."""

    async def classify(self, stock_id: str, articles: list[Article]) -> list[SentimentClassification]:
        """
        Classifies each post's stance toward stock_id, at most one result per post.
        A post the classifier could not read is left out. Raises when no post could be classified.
        """
        ...
