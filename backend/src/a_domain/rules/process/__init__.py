"""
Process Rules.

Contains all rules for the "Process" phase of the pipeline:
- indicators/: Technical analysis rules (trend, momentum, volume, etc.)
- policies/: Screening policies that orchestrate rules
- scoring/: Score calculation rules
- ai/: AI prompt building and response parsing
"""
from backend.src.a_domain.rules.process.indicators import (
    AdxDirectionRule,
    AdxTrendStrengthRule,
    AtrRangeRule,
    BollingerPositionRule,
    BollingerSqueezeRule,
    BollingerThresholdRule,
    ConsecutiveUpDaysRule,
    DailyRangeRule,
    GapRule,
    GoldenCrossRule,
    IntradayMomentumRule,
    IntradayRangeRule,
    LiquidityRule,
    MaAlignmentRule,
    MacdCrossRule,
    MacdHistogramRule,
    MacdPositiveRule,
    MfiThresholdRule,
    MinimumPriceRule,
    ObvTrendRule,
    PriceAboveMaRule,
    PriceDropRule,
    RsiRangeRule,
    StochasticCrossRule,
    StochasticThresholdRule,
    VolumeConfirmationRule,
    VolumeRatioRule,
)
from backend.src.a_domain.rules.process.policies import TechnicalScreeningPolicy

__all__ = [
    # Trend
    "PriceAboveMaRule",
    "MaAlignmentRule",
    "GoldenCrossRule",
    "AdxTrendStrengthRule",
    "AdxDirectionRule",
    # Momentum
    "RsiRangeRule",
    "MacdCrossRule",
    "MacdPositiveRule",
    "MacdHistogramRule",
    "StochasticThresholdRule",
    "StochasticCrossRule",
    "MfiThresholdRule",
    # Volume
    "VolumeRatioRule",
    "ObvTrendRule",
    "LiquidityRule",
    "MinimumPriceRule",
    # Volatility
    "BollingerThresholdRule",
    "BollingerPositionRule",
    "BollingerSqueezeRule",
    "AtrRangeRule",
    "DailyRangeRule",
    # Entry Timing
    "PriceDropRule",
    "IntradayMomentumRule",
    "VolumeConfirmationRule",
    "GapRule",
    "IntradayRangeRule",
    "ConsecutiveUpDaysRule",
    # Policy
    "TechnicalScreeningPolicy",
]
