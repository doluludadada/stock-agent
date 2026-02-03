"""
Screening Policy Factory.

This factory creates different TechnicalScreeningPolicy configurations
based on trading strategy and risk tolerance.

Trading Strategies:
1. Conservative: More filters, fewer trades, higher win rate
2. Moderate: Balanced approach
3. Aggressive: Fewer filters, more trades, lower win rate

Reference:
- Van Tharp (2006). Trade Your Way to Financial Freedom.
  "Your trading system must match your psychology."
"""

from backend.src.a_domain.rules.base import TradingRule
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
    AdxTrendStrengthRule,  # Todo: I guess i need this rule, right?
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
from backend.src.a_domain.rules.process.policies.technical_screening import TechnicalScreeningPolicy

# TODO: Refactor this file, i dont like lots of tons functions, combain it to a class


def create_conservative_policy() -> TechnicalScreeningPolicy:
    """
    Conservative Strategy: High win rate, fewer trades.

    Best for:
    - Beginners
    - Large accounts (can't afford drawdowns)
    - Part-time traders

    Expected Performance:
    - Win rate: 60-70%
    - Trades per week: 2-5
    - Risk per trade: 1%
    """
    setup_rules: list[TradingRule] = [
        # Trend (all must pass)
        PriceAboveMa20Rule(),
        PriceAboveMa60Rule(),
        MaBullishAlignmentRule(),
        # Momentum (both must pass)
        MacdBullishRule(),
        MacdPositiveRule(),
        RsiHealthyRule(min_rsi=50, max_rsi=65),  # Tighter range
    ]

    safety_rules: list[TradingRule] = [
        # Risk management (all must pass)
        RsiNotOverboughtRule(max_rsi=75),  # More conservative
        StochasticNotOverboughtRule(),
        BollingerNotOverboughtRule(max_percent_b=0.85),
        VolatilityNotExtremeRule(max_daily_range_pct=0.05),
        LiquidityRule(min_daily_volume=1000),  # Higher liquidity
        MinimumPriceRule(min_price=20.0),
        VolumeNotDryRule(min_ratio=0.7),  # More volume required
    ]

    entry_timing_rules: list[TradingRule] = [
        NotCrashingRule(max_drop_pct=0.02),  # Tighter
        IntradayMomentumRule(),
        VolumeConfirmationRule(min_volume_ratio=0.7),
        NotGappedUpExcessivelyRule(max_gap_pct=0.02),
        IntradayRangePositionRule(max_range_position=0.7),
        ConsecutiveUpDaysRule(max_consecutive_up=3),  # More conservative
    ]

    return TechnicalScreeningPolicy(
        setup_rules=setup_rules,
        safety_rules=safety_rules,
        entry_timing_rules=entry_timing_rules,
    )


def create_moderate_policy() -> TechnicalScreeningPolicy:
    """
    Moderate Strategy: Balanced approach.

    Best for:
    - Experienced traders
    - Medium-sized accounts
    - Active traders with time to monitor

    Expected Performance:
    - Win rate: 50-60%
    - Trades per week: 5-10
    - Risk per trade: 2%
    """
    setup_rules: list[TradingRule] = [
        # Trend
        PriceAboveMa20Rule(),
        MaBullishAlignmentRule(),
        # Momentum
        MacdBullishRule(),
        RsiBullishMomentumRule(),  # Just above 50
    ]

    safety_rules: list[TradingRule] = [
        RsiNotOverboughtRule(max_rsi=80),
        VolatilityNotExtremeRule(max_daily_range_pct=0.07),
        LiquidityRule(min_daily_volume=500),
        MinimumPriceRule(min_price=15.0),
        VolumeNotDryRule(min_ratio=0.5),
    ]

    entry_timing_rules: list[TradingRule] = [
        NotCrashingRule(max_drop_pct=0.03),
        IntradayMomentumRule(),
        VolumeConfirmationRule(min_volume_ratio=0.5),
        ConsecutiveUpDaysRule(max_consecutive_up=4),
    ]

    return TechnicalScreeningPolicy(
        setup_rules=setup_rules,
        safety_rules=safety_rules,
        entry_timing_rules=entry_timing_rules,
    )


def create_aggressive_policy() -> TechnicalScreeningPolicy:
    """
    Aggressive Strategy: More trades, lower win rate.

    Best for:
    - Experienced scalpers
    - Small accounts (need more opportunities)
    - Full-time traders

    Expected Performance:
    - Win rate: 40-50%
    - Trades per week: 10-20
    - Risk per trade: 1-2% (strict stop loss essential)

    WARNING: Requires excellent risk management!
    """
    setup_rules: list[TradingRule] = [
        # Minimal trend requirement
        PriceAboveMa20Rule(),
        MacdBullishRule(),
    ]

    safety_rules: list[TradingRule] = [
        # Basic safety only
        RsiNotOverboughtRule(max_rsi=85),  # Allow higher RSI
        LiquidityRule(min_daily_volume=300),
        MinimumPriceRule(min_price=10.0),
    ]

    entry_timing_rules: list[TradingRule] = [
        NotCrashingRule(max_drop_pct=0.05),  # Allow more volatility
        VolumeConfirmationRule(min_volume_ratio=0.3),
    ]

    return TechnicalScreeningPolicy(
        setup_rules=setup_rules,
        safety_rules=safety_rules,
        entry_timing_rules=entry_timing_rules,
    )


def create_buzz_stock_policy() -> TechnicalScreeningPolicy:
    """
    Buzz Stock Strategy: For social media trending stocks.

    These stocks already have momentum (social proof).
    We only need to ensure safety and timing.

    Best for:
    - Trading hot stocks from PTT/Twitter
    - Momentum plays
    - News-driven moves

    WARNING: Higher risk! Use strict stop loss.
    """
    # No setup rules - buzz provides the setup
    setup_rules: list[TradingRule] = []

    safety_rules: list[TradingRule] = [
        # Critical safety checks
        RsiNotOverboughtRule(max_rsi=80),  # Not too extended
        VolatilityNotExtremeRule(max_daily_range_pct=0.10),  # Allow volatility
        LiquidityRule(min_daily_volume=500),  # Need exit liquidity
        MinimumPriceRule(min_price=10.0),
    ]

    entry_timing_rules: list[TradingRule] = [
        NotCrashingRule(max_drop_pct=0.03),  # Don't catch falling knife
        IntradayMomentumRule(),  # Must show strength
        VolumeConfirmationRule(min_volume_ratio=1.0),  # Need HIGH volume
    ]

    return TechnicalScreeningPolicy(
        setup_rules=setup_rules,
        safety_rules=safety_rules,
        entry_timing_rules=entry_timing_rules,
    )


def create_nightly_screening_policy() -> TechnicalScreeningPolicy:
    """
    Nightly Screening: For generating the technical watchlist.

    This runs after market close on historical data.
    No entry timing rules needed.

    Purpose: Find stocks with good SETUPS for tomorrow.
    """
    setup_rules: list[TradingRule] = [
        # Trend confirmation
        PriceAboveMa20Rule(),
        MaBullishAlignmentRule(),
        # Momentum confirmation
        MacdBullishRule(),
        RsiBullishMomentumRule(),
    ]

    safety_rules: list[TradingRule] = [
        RsiNotOverboughtRule(max_rsi=75),
        LiquidityRule(min_daily_volume=500),
        MinimumPriceRule(min_price=15.0),
        VolumeAboveAverageRule(min_ratio=0.8),
    ]

    # No entry timing rules for nightly
    return TechnicalScreeningPolicy(
        setup_rules=setup_rules,
        safety_rules=safety_rules,
        entry_timing_rules=[],
    )


# --- Quick Access Configurations ---

CONSERVATIVE = create_conservative_policy
MODERATE = create_moderate_policy
AGGRESSIVE = create_aggressive_policy
BUZZ_STOCK = create_buzz_stock_policy
NIGHTLY = create_nightly_screening_policy


