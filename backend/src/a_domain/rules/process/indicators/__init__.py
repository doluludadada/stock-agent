"""
Technical Analysis Indicators.

This package contains all technical analysis rules organized by category.

Categories:
- trend: Trend following rules (MA, ADX)
- momentum: Momentum oscillators (RSI, MACD, Stochastic)
- volume: Volume confirmation rules
- volatility: Volatility rules (Bollinger, ATR)
- entry_timing: Intraday entry timing rules
"""
from backend.src.a_domain.rules.process.indicators.entry_timing import (
    ConsecutiveUpDaysRule,
    IntradayMomentumRule,
    IntradayRangePositionRule,
    NotCrashingRule,
    NotGappedUpExcessivelyRule,
    VolumeConfirmationRule,
)
from backend.src.a_domain.rules.process.indicators.momentum import (
    MacdBullishRule,
    MacdPositiveRule,
    RsiBullishMomentumRule,
    RsiHealthyRule,
    RsiNotOverboughtRule,
    StochasticNotOverboughtRule,
)
from backend.src.a_domain.rules.process.indicators.trend import (
    AdxTrendStrengthRule,
    GoldenCrossRule,
    MaBullishAlignmentRule,
    PriceAboveMa20Rule,
    PriceAboveMa60Rule,
)
from backend.src.a_domain.rules.process.indicators.volatility import (
    BollingerNotOverboughtRule,
    VolatilityNotExtremeRule,
)
from backend.src.a_domain.rules.process.indicators.volume import (
    LiquidityRule,
    MinimumPriceRule,
    VolumeAboveAverageRule,
    VolumeNotDryRule,
)

__all__ = [
    # Trend
    "PriceAboveMa20Rule",
    "PriceAboveMa60Rule",
    "MaBullishAlignmentRule",
    "GoldenCrossRule",
    "AdxTrendStrengthRule",
    # Momentum
    "RsiHealthyRule",
    "RsiNotOverboughtRule",
    "RsiBullishMomentumRule",
    "MacdBullishRule",
    "MacdPositiveRule",
    "StochasticNotOverboughtRule",
    # Volume
    "VolumeAboveAverageRule",
    "VolumeNotDryRule",
    "LiquidityRule",
    "MinimumPriceRule",
    # Volatility
    "BollingerNotOverboughtRule",
    "VolatilityNotExtremeRule",
    # Entry Timing
    "NotCrashingRule",
    "IntradayMomentumRule",
    "VolumeConfirmationRule",
    "NotGappedUpExcessivelyRule",
    "IntradayRangePositionRule",
    "ConsecutiveUpDaysRule",
]


