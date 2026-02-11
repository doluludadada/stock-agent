"""
Application-layer factories for assembling domain objects.

These decide WHICH rules go in WHICH tier — an orchestration decision,
not a business rule.
"""
from backend.src.b_application.factories.policy_factory import (
    create_aggressive_policy,
    create_buzz_stock_policy,
    create_conservative_policy,
    create_moderate_policy,
    create_nightly_screening_policy,
)

__all__ = [
    "create_conservative_policy",
    "create_moderate_policy",
    "create_aggressive_policy",
    "create_buzz_stock_policy",
    "create_nightly_screening_policy",
]
