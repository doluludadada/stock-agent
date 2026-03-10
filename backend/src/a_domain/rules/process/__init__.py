"""
Process Rules.

Import rules from their category packages directly:
    from a_domain.rules.process.indicators.trend import PriceAboveMaRule
    from a_domain.rules.process.policies import TechnicalScreeningPolicy
"""
from a_domain.rules.process.policies import TechnicalScreeningPolicy

__all__ = ["TechnicalScreeningPolicy"]
