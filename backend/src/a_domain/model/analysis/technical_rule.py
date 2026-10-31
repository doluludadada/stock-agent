from dataclasses import dataclass

from a_domain.rules.technical.criteria.base import TechnicalCriterion
from a_domain.types.enums import RuleEffect


@dataclass(frozen=True)
class TechnicalRule:
    """One criterion of a strategy and what its result does to the stock."""

    criterion: TechnicalCriterion
    effect: RuleEffect
