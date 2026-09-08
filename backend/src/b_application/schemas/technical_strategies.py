# backend/src/b_application/schemas/technical_strategies.py

from dataclasses import dataclass

from a_domain.rules.technical.strategy import TechnicalStrategy
from a_domain.types.enums import StrategyName


@dataclass(frozen=True)
class TechnicalStrategies:
    """
    Technical strategies prepared by the composition root.

    Pipeline chooses the strategy for each workflow while TechnicalFilter
    remains reusable and strategy-agnostic.
    """

    active_name: StrategyName
    active: TechnicalStrategy
    buzz: TechnicalStrategy
