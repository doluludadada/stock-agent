from dataclasses import dataclass

import icontract


@icontract.invariant(lambda self: self.technical_weight >= 0)
@icontract.invariant(lambda self: self.sentiment_weight >= 0)
@icontract.invariant(lambda self: self.technical_weight + self.sentiment_weight > 0)
@dataclass(frozen=True)
class CompositeScoreRule:
    """Combines technical and AI scores into one final score."""

    technical_weight: float
    sentiment_weight: float

    @icontract.require(lambda technical_score: 0 <= technical_score <= 100)
    @icontract.require(lambda ai_score: 0 <= ai_score <= 100)
    @icontract.ensure(lambda result: 0 <= result <= 100)
    def calculate(
        self,
        technical_score: int,
        ai_score: int,
    ) -> int:
        total_weight = self.technical_weight + self.sentiment_weight

        return round((technical_score * self.technical_weight + ai_score * self.sentiment_weight) / total_weight)
