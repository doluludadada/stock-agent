class CompositeScoreRule:
    """Combines Technical and Sentiment scores into a final weighted score."""

    def __init__(self, technical_weight: float = 0.6, sentiment_weight: float = 0.4):
        self._technical_weight = technical_weight
        self._sentiment_weight = sentiment_weight

    def calculate(self, technical_score: int | None, sentiment_score: int | None) -> int:
        # TODO: Maybe more cleaner. it cannot be None.
        tech = technical_score if technical_score is not None else 50
        sent = sentiment_score if sentiment_score is not None else 50
        combined = (tech * self._technical_weight) + (sent * self._sentiment_weight)

        final_score = int(max(0, min(100, combined)))

        # --- The AI Veto Gate ---
        # If the math says BUY (>= 70) but the AI hates the fundamentals (< 50)
        # We strictly downgrade the score to 69 (Highest possible HOLD)
        # TODO: Remove hard code?
        if final_score >= 70 and sent < 50:
            return 69

        return final_score
