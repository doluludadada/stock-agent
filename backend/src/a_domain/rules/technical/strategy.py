# backend/src/a_domain/rules/technical/strategy.py

from dataclasses import dataclass

from icontract import invariant

from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.market.stock import Stock
from a_domain.rules.technical.criteria.base import TechnicalCriterion


@invariant(lambda self: 0 <= self.base_score <= 100)
@invariant(lambda self: self.hard_failure_penalty >= 0)
@invariant(lambda self: self.soft_failure_penalty >= 0)
@invariant(lambda self: self.observation_bonus >= 0)
@dataclass(frozen=True)
class TechnicalStrategy:
    """
    Defines how a stock is evaluated technically.

    must_pass:
        Required conditions. Any failure rejects the stock.

    should_pass:
        Preferred conditions. Failures reduce the technical score
        without rejecting the stock.

    observe:
        Positive technical signals used for reporting
        and additional scoring.
    """

    must_pass: list[TechnicalCriterion]
    should_pass: list[TechnicalCriterion]
    observe: list[TechnicalCriterion]

    base_score: int
    hard_failure_penalty: int
    soft_failure_penalty: int
    observation_bonus: int

    def evaluate(self, stock: Stock) -> TechnicalReport:
        hard_failures: list[str] = []
        soft_failures: list[str] = []
        observations: list[str] = []
        score = self.base_score

        for criterion in self.must_pass:
            if not criterion.apply(stock):
                hard_failures.append(criterion.name)
                score -= self.hard_failure_penalty

        for criterion in self.should_pass:
            if not criterion.apply(stock):
                soft_failures.append(criterion.name)
                score -= self.soft_failure_penalty

        for criterion in self.observe:
            detected = criterion.apply(stock)
            observations.append(f"{criterion.name}: {'detected' if detected else 'not detected'}")
            if detected:
                score += self.observation_bonus

        return TechnicalReport(
            score=max(0, min(100, score)),
            hard_failures=hard_failures,
            soft_failures=soft_failures,
            observations=observations,
        )
