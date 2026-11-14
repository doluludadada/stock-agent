from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from a_domain.types.values import NonEmptyText, Score


@dataclass(frozen=True)
class TechnicalObservation:
    """Whether the pattern of a rule that adds to the score showed. `rule` is the rule's name in its strategy."""

    rule: NonEmptyText
    detected: bool

    @property
    def sentence(self) -> str:
        return f"{self.rule}: {'detected' if self.detected else 'not detected'}"


@dataclass(frozen=True, config=ConfigDict(json_schema_serialization_defaults_required=True))
class TechnicalReport:
    """
    Result produced by a TechnicalStrategy.

    Hard failures reject the stock.
    Soft failures reduce technical quality without rejecting the stock.
    Observations say, for each rule that adds to the score, whether its pattern showed.
    """

    score: Score[int]
    hard_failures: list[str] = Field(default_factory=list)
    soft_failures: list[str] = Field(default_factory=list)
    observations: list[TechnicalObservation] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.hard_failures
