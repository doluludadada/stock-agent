"""
Example: Dependency injection for TechnicalScreeningPolicy.

This shows how to wire up the policy with different rule sets.
"""
from src.a_domain.rules.process import (
    BullishMacdCrossoverRule,
    IntradayMomentumRule,
    NotCrashingRule,
    PriceAboveMovingAverageRule,
    RsiHealthyRule,
    TechnicalScreeningPolicy,
    VolumeConfirmationRule,
)


def get_screening_policy() -> TechnicalScreeningPolicy:
    """
    Factory for TechnicalScreeningPolicy with all rule sets.
    
    Rule Application:
    - standard_rules: Full technical validation for TECHNICAL_WATCHLIST stocks
    - safety_rules: Lighter validation for SOCIAL_BUZZ stocks
    - entry_timing_rules: Intraday-only rules (applied when is_intraday=True)
    """
    
    # Setup rules: "Is this stock in a good trend?"
    standard_rules = [
        PriceAboveMovingAverageRule(),  # Price > MA20
        BullishMacdCrossoverRule(),      # MACD Line > Signal
        RsiHealthyRule(),                # RSI between 50-85
    ]
    
    # Safety rules for buzz stocks: "Is it safe to enter?"
    safety_rules = [
        RsiHealthyRule(),  # At minimum, RSI should not be overbought
    ]
    
    # Entry timing rules: "Is NOW the right moment?"
    entry_timing_rules = [
        NotCrashingRule(max_drop_pct=0.03),       # Not falling > 3% today
        VolumeConfirmationRule(min_volume_ratio=0.5),  # Volume > 50% of avg
        IntradayMomentumRule(),                   # Price > Today's open
    ]
    
    return TechnicalScreeningPolicy(
        standard_rules=standard_rules,
        safety_rules=safety_rules,
        entry_timing_rules=entry_timing_rules,
    )


def get_nightly_screening_policy() -> TechnicalScreeningPolicy:
    """
    Factory for nightly screening (no entry timing rules needed).
    
    Use this when running GenerateWatchlist at night.
    Pass is_intraday=False to the evaluate method.
    """
    standard_rules = [
        PriceAboveMovingAverageRule(),
        BullishMacdCrossoverRule(),
        RsiHealthyRule(),
    ]
    
    safety_rules = [
        RsiHealthyRule(),
    ]
    
    # No entry timing rules for nightly
    return TechnicalScreeningPolicy(
        standard_rules=standard_rules,
        safety_rules=safety_rules,
        entry_timing_rules=[],  # Empty for nightly
    )
