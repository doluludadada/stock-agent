"""
Process Rules.

This package contains all rules for the "Process" phase of the pipeline:
1. Technical Screening (Filter candidates)
2. Scoring (Calculate technical/sentiment scores)
3. AI Analysis (Sentiment prompts and parsing)

Sub-packages:
- indicators/: Technical analysis rules (trend, momentum, volume, etc.)
- policies/: Screening policies that orchestrate rules
- scoring/: Score calculation rules
- ai/: AI prompt building and response parsing
"""
# Indicators (all technical rules)
from src.a_domain.rules.process.indicators import (
    AdxTrendStrengthRule,
    BollingerNotOverboughtRule,
    ConsecutiveUpDaysRule,
    GoldenCrossRule,
    IntradayMomentumRule,
    IntradayRangePositionRule,
    LiquidityRule,
    MaBullishAlignmentRule,
    MacdBullishRule,
    MacdPositiveRule,
    MinimumPriceRule,
    NotCrashingRule,
    NotGappedUpExcessivelyRule,
    PriceAboveMa20Rule,
    PriceAboveMa60Rule,
    RsiBullishMomentumRule,
    RsiHealthyRule,
    RsiNotOverboughtRule,
    StochasticNotOverboughtRule,
    VolatilityNotExtremeRule,
    VolumeAboveAverageRule,
    VolumeConfirmationRule,
    VolumeNotDryRule,
)

# Policies
from src.a_domain.rules.process.policies import (
    AGGRESSIVE,
    BUZZ_STOCK,
    CONSERVATIVE,
    MODERATE,
    NIGHTLY,
    TechnicalScreeningPolicy,
    create_aggressive_policy,
    create_buzz_stock_policy,
    create_conservative_policy,
    create_moderate_policy,
    create_nightly_screening_policy,
)

__all__ = [
    # === Trend Rules ===
    "PriceAboveMa20Rule",
    "PriceAboveMa60Rule",
    "MaBullishAlignmentRule",
    "GoldenCrossRule",
    "AdxTrendStrengthRule",
    
    # === Momentum Rules ===
    "RsiHealthyRule",
    "RsiNotOverboughtRule",
    "RsiBullishMomentumRule",
    "MacdBullishRule",
    "MacdPositiveRule",
    "StochasticNotOverboughtRule",
    
    # === Volume Rules ===
    "VolumeAboveAverageRule",
    "VolumeNotDryRule",
    "LiquidityRule",
    "MinimumPriceRule",
    
    # === Volatility Rules ===
    "BollingerNotOverboughtRule",
    "VolatilityNotExtremeRule",
    
    # === Entry Timing Rules ===
    "NotCrashingRule",
    "IntradayMomentumRule",
    "VolumeConfirmationRule",
    "NotGappedUpExcessivelyRule",
    "IntradayRangePositionRule",
    "ConsecutiveUpDaysRule",
    
    # === Policies ===
    "TechnicalScreeningPolicy",
    "create_conservative_policy",
    "create_moderate_policy",
    "create_aggressive_policy",
    "create_buzz_stock_policy",
    "create_nightly_screening_policy",
    "CONSERVATIVE",
    "MODERATE",
    "AGGRESSIVE",
    "BUZZ_STOCK",
    "NIGHTLY",
]
