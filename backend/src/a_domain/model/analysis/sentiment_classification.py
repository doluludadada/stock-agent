from dataclasses import dataclass

from icontract import invariant

from a_domain.types.enums import SentimentLabel


@invariant(lambda self: 0.0 <= self.confidence <= 1.0, "confidence must be 0-1")
@dataclass(frozen=True)
class SentimentClassification:
    """One post's classified stance."""

    label: SentimentLabel
    confidence: float
