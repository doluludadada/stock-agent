class CompositeScoreRule:
    """
    Rule: Combines Technical and Sentiment scores into a final weighted score.
    """

    def __init__(self, technical_weight: float = 0.6, sentiment_weight: float = 0.4):
        total_weight = technical_weight + sentiment_weight
        if total_weight > 0:
            self._technical_weight = technical_weight / total_weight
            self._sentiment_weight = sentiment_weight / total_weight
        else:
            self._technical_weight = 0.5
            self._sentiment_weight = 0.5

    def calculate(self, technical_score: int | None, sentiment_score: int | None) -> int:
        normalised_technical = technical_score if technical_score is not None else 50
        normalised_sentiment = sentiment_score if sentiment_score is not None else 50

        combined_score = (normalised_technical * self._technical_weight) + (
            normalised_sentiment * self._sentiment_weight
        )

        return int(max(0, min(100, combined_score)))


