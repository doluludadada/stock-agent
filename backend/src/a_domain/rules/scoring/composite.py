from dataclasses import dataclass

from a_domain.model.market.stock import Stock


@dataclass(frozen=True)
class CompositeScoreRule:
    """
    Combines technical score and AI sentiment score into one 0-100 score.
    """

    technical_weight: float
    sentiment_weight: float

    def calculate(self, stock: Stock) -> int:
        # TODO: Shoudn't be None no?
        technical_score = stock.technical_score if stock.technical_score is not None else 50
        ai_score = stock.ai_score if stock.ai_score is not None else 50

        total_weight = self.technical_weight + self.sentiment_weight

        if total_weight <= 0:
            return 50

        weighted_score = (technical_score * self.technical_weight + ai_score * self.sentiment_weight) / total_weight

        return self._clamp(round(weighted_score))

    def _clamp(self, score: int) -> int:
        return max(0, min(100, score))
