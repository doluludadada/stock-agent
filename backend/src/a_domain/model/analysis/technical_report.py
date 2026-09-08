# backend/src/a_domain/model/analysis/technical_report.pyl
from dataclasses import dataclass, field

from icontract import invariant


@invariant(lambda self: 0 <= self.score <= 100, "Technical score must be 0-100")
@dataclass
class TechnicalReport:
    """
    Result produced by a TechnicalStrategy.

    Hard failures reject the stock.
    Soft failures reduce technical quality without rejecting the stock.
    Observations describe optional technical signals.
    """

    score: int
    hard_failures: list[str] = field(default_factory=list)
    soft_failures: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.hard_failures
