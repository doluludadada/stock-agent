"""
Trend Following Rules.

Reference: Murphy, J. (1999). Technical Analysis of the Financial Markets.
"""
from backend.src.a_domain.rules.process.indicators.trend.trend_rules import (
    AdxBullishDirectionRule,
    AdxTrendStrengthRule,
    GoldenCrossRule,
    MaBullishAlignmentRule,
    PriceAboveMa20Rule,
    PriceAboveMa60Rule,
)

__all__ = [
    "PriceAboveMa20Rule",
    "PriceAboveMa60Rule",
    "MaBullishAlignmentRule",
    "GoldenCrossRule",
    "AdxTrendStrengthRule",
    "AdxBullishDirectionRule",
]


