from dataclasses import dataclass

from icontract import invariant


@invariant(lambda self: 0 <= self.base_score <= 100)
@invariant(lambda self: self.block_failure_penalty >= 0)
@invariant(lambda self: self.failure_score_reduction >= 0)
@invariant(lambda self: self.pass_score_increase >= 0)
@dataclass(frozen=True)
class TechnicalScoring:
    """How a strategy's rule results move the technical score, which starts at `base_score`."""

    base_score: int = 50
    block_failure_penalty: int = 15
    failure_score_reduction: int = 5
    pass_score_increase: int = 5
