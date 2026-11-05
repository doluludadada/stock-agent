from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from a_domain.types.values import Score


@dataclass(frozen=True, config=ConfigDict(json_schema_serialization_defaults_required=True))
class TechnicalReport:
    """
    Result produced by a TechnicalStrategy.

    Hard failures reject the stock.
    Soft failures reduce technical quality without rejecting the stock.
    Observations describe optional technical signals.
    """

    score: Score[int]
    hard_failures: list[str] = Field(default_factory=list)
    soft_failures: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.hard_failures
