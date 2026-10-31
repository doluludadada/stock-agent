# backend/src/a_domain/rules/technical/strategy.py

from dataclasses import dataclass

from icontract import invariant

from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.analysis.technical_rule import TechnicalRule
from a_domain.model.analysis.technical_scoring import TechnicalScoring
from a_domain.model.indicators.indicator_parameters import IndicatorParameters
from a_domain.model.market.stock import Stock
from a_domain.types.enums import RuleEffect


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

    def apply(self, stock: Stock) -> TechnicalReport:
        hard_failures: list[str] = []
        soft_failures: list[str] = []
        observations: list[str] = []
        score = self.scoring.base_score

        for rule in self.rules:
            passed = rule.criterion.apply(stock)

            if rule.effect == RuleEffect.BLOCK_ON_FAIL and not passed:
                hard_failures.append(str(rule.criterion))
                score -= self.scoring.block_failure_penalty
                continue

            if rule.effect == RuleEffect.REDUCE_SCORE_ON_FAIL and not passed:
                soft_failures.append(str(rule.criterion))
                score -= self.scoring.failure_score_reduction
                continue

            if rule.effect == RuleEffect.INCREASE_SCORE_ON_PASS:
                result = "detected" if passed else "not detected"
                observations.append(f"{rule.criterion}: {result}")
                score += self.scoring.pass_score_increase if passed else 0

        return TechnicalReport(
            score=max(0, min(100, score)), hard_failures=hard_failures, soft_failures=soft_failures, observations=observations
        )
