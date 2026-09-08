from dataclasses import dataclass

from icontract import invariant


@invariant(lambda self: 0 <= self.technical_weight <= 1)
@invariant(lambda self: 0 <= self.ai_weight <= 1)
@invariant(lambda self: abs(self.technical_weight + self.ai_weight - 1) < 0.001)
@dataclass(frozen=True)
class CompositeScoreRule:
    """Combines technical and AI scores into one final score."""

    technical_weight: float
    ai_weight: float

    def calculate(
        self,
        technical_score: int,
        ai_score: int,
    ) -> int:
        score = technical_score * self.technical_weight + ai_score * self.ai_weight

        return round(score)
