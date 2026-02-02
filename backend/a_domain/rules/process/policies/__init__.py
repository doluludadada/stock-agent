"""
Screening Policies.

Policies orchestrate multiple rules into a trading strategy.
"""
from src.a_domain.rules.process.policies.policy_factory import (
    AGGRESSIVE,
    BUZZ_STOCK,
    CONSERVATIVE,
    MODERATE,
    NIGHTLY,
    create_aggressive_policy,
    create_buzz_stock_policy,
    create_conservative_policy,
    create_moderate_policy,
    create_nightly_screening_policy,
)
from src.a_domain.rules.process.policies.technical_screening import TechnicalScreeningPolicy

__all__ = [
    "TechnicalScreeningPolicy",
    # Factory functions
    "create_conservative_policy",
    "create_moderate_policy",
    "create_aggressive_policy",
    "create_buzz_stock_policy",
    "create_nightly_screening_policy",
    # Quick access
    "CONSERVATIVE",
    "MODERATE",
    "AGGRESSIVE",
    "BUZZ_STOCK",
    "NIGHTLY",
]
