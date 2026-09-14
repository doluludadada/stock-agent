# backend/src/a_domain/rules/technical/strategy.py

from dataclasses import dataclass

from icontract import invariant

from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.market.stock import Stock
from a_domain.rules.technical.calculation.parameters import IndicatorParameters
from a_domain.rules.technical.criteria.base import TechnicalCriterion
from a_domain.types.enums import RuleEffect


@invariant(lambda self: 0 <= self.base_score <= 100)
@invariant(lambda self: self.block_failure_penalty >= 0)
@invariant(lambda self: self.failure_score_reduction >= 0)
@invariant(lambda self: self.pass_score_increase >= 0)
@dataclass(frozen=True)
class TechnicalScoring:
    base_score: int = 50
    block_failure_penalty: int = 15
    failure_score_reduction: int = 5
    pass_score_increase: int = 5


@dataclass(frozen=True)
class TechnicalRule:
    criterion: TechnicalCriterion
    effect: RuleEffect


@invariant(lambda self: bool(self.strategy_id.strip()))
@invariant(lambda self: len(self.rules) > 0)
@dataclass(frozen=True)
class TechnicalStrategy:
    """
    Complete executable technical strategy.

    Indicator parameters define how indicators are calculated.
    Rules define which criteria are evaluated and how each result affects
    eligibility and technical scoring.
    """

    strategy_id: str
    indicators: IndicatorParameters
    scoring: TechnicalScoring
    rules: tuple[TechnicalRule, ...]

    def evaluate(self, stock: Stock) -> TechnicalReport:
        hard_failures: list[str] = []
        soft_failures: list[str] = []
        observations: list[str] = []
        score = self.scoring.base_score

        for rule in self.rules:
            passed = rule.criterion.apply(stock)

            if rule.effect == RuleEffect.BLOCK_ON_FAIL and not passed:
                hard_failures.append(rule.criterion.name)
                score -= self.scoring.block_failure_penalty
                continue

            if rule.effect == RuleEffect.REDUCE_SCORE_ON_FAIL and not passed:
                soft_failures.append(rule.criterion.name)
                score -= self.scoring.failure_score_reduction
                continue

            if rule.effect == RuleEffect.INCREASE_SCORE_ON_PASS:
                result = "detected" if passed else "not detected"
                observations.append(f"{rule.criterion.name}: {result}")
                score += self.scoring.pass_score_increase if passed else 0

        return TechnicalReport(
            score=max(0, min(100, score)),
            hard_failures=hard_failures,
            soft_failures=soft_failures,
            observations=observations,
        )
