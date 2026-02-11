"""
Technical Analysis Indicators.

All rules organized by category:
- trend: Trend following rules (MA, ADX)
- momentum: Momentum oscillators (RSI, MACD, Stochastic)
- volume: Volume confirmation rules
- volatility: Volatility rules (Bollinger, ATR)
- entry_timing: Intraday entry timing rules
"""
from backend.src.a_domain.rules.process.indicators.entry_timing import (
    ConsecutiveUpDaysRule,
    GapRule,
    IntradayMomentumRule,
    IntradayRangeRule,
    PriceDropRule,
    VolumeConfirmationRule,
)
from backend.src.a_domain.rules.process.indicators.momentum import (
    MacdCrossRule,
    MacdHistogramRule,
    MacdPositiveRule,
    MfiThresholdRule,
    RsiRangeRule,
    StochasticCrossRule,
    StochasticThresholdRule,
)
from backend.src.a_domain.rules.process.indicators.trend import (
    AdxDirectionRule,
    AdxTrendStrengthRule,
    GoldenCrossRule,
    MaAlignmentRule,
    PriceAboveMaRule,
)
from backend.src.a_domain.rules.process.indicators.volatility import (
    AtrRangeRule,
    BollingerPositionRule,
    BollingerSqueezeRule,
    BollingerThresholdRule,
    DailyRangeRule,
)
from backend.src.a_domain.rules.process.indicators.volume import (
    LiquidityRule,
    MinimumPriceRule,
    ObvTrendRule,
    VolumeRatioRule,
)

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
]
