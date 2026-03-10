class CompositeScoreRule:
    """Combines Technical and Sentiment scores into a final weighted score."""

    def __init__(self, technical_weight: float = 0.6, sentiment_weight: float = 0.4):
        self._technical_weight = technical_weight
        self._sentiment_weight = sentiment_weight

    def calculate(self, technical_score: int | None, sentiment_score: int | None) -> int:
        tech = technical_score if technical_score is not None else 50
        sent = sentiment_score if sentiment_score is not None else 50
        combined = (tech * self._technical_weight) + (sent * self._sentiment_weight)
        return int(max(0, min(100, combined)))
