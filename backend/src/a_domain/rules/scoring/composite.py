from typing import Self

from pydantic import model_validator
from pydantic.dataclasses import dataclass

from a_domain.types.values import Fraction


@dataclass(frozen=True)
class CompositeScoreRule:
    """Combines technical and AI scores into one final score."""

    technical_weight: Fraction
    ai_weight: Fraction

    @model_validator(mode="after")
    def _weights_add_up_to_one(self) -> Self:
        if abs(self.technical_weight + self.ai_weight - 1) >= 0.001:
            raise ValueError("the technical and AI weights must add up to 1")

        return self

    def apply(self, technical_score: int, ai_score: int) -> int:
        score = technical_score * self.technical_weight + ai_score * self.ai_weight

        return round(score)
