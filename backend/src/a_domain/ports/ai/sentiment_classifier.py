from typing import Protocol

from a_domain.model.market.article import Article


class ISentimentClassifier(Protocol):
    """Classifies social posts, so the model behind it can be replaced."""

    async def classify(self, stock_id: str, posts: list[Article]) -> list[Article]:
        """
        Reads each post's stance toward stock_id and returns each post it could classify, as a copy with its sentiment
        set, at most one copy per post. A post the classifier could not read is left out. Raises when it had posts to
        classify and could classify none of them.
        """
        ...
