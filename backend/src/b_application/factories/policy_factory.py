"""
Screening Policy Factory.

Application layer: decides WHICH rules go in WHICH tier for each strategy.
All threshold values are injected via StrategyThresholds — no magic numbers.

Trading Strategies:
1. Conservative: More hard gates, fewer trades, higher win rate
2. Moderate: Balanced approach
3. Aggressive: Fewer hard gates, more trades
4. Buzz Stock: For social media trending stocks
5. Nightly: For after-hours watchlist generation (no entry timing)
"""
from pathlib import Path

import yaml
from backend.src.a_domain.rules.base import TradingRule
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
from backend.src.a_domain.rules.process.policies import TechnicalScreeningPolicy
from backend.src.a_domain.types.enums import MaPeriod
from backend.src.b_application.schemas.config import StrategyThresholds


def create_conservative_policy(
    cfg: StrategyThresholds,
) -> TechnicalScreeningPolicy:
    """
    Conservative Strategy: High win rate, fewer trades.

    Expected: Win rate 60-70%, 2-5 trades/week, 1% risk/trade.
    """
    return TechnicalScreeningPolicy(
        setup_must_pass=[
            PriceAboveMaRule(MaPeriod.MA_20),
            PriceAboveMaRule(MaPeriod.MA_60),
            MaAlignmentRule(MaPeriod.MA_20, MaPeriod.MA_60),
            MacdCrossRule(),
            MacdPositiveRule(),
            RsiRangeRule(min_rsi=cfg.rsi_healthy_min, max_rsi=cfg.rsi_healthy_max),
        ],
        safety_must_pass=[
            RsiRangeRule(max_rsi=cfg.rsi_overbought),
            StochasticThresholdRule(threshold=cfg.stoch_overbought),
            BollingerThresholdRule(max_percent_b=cfg.bollinger_max_pct_b),
            DailyRangeRule(max_daily_range_pct=cfg.max_daily_volatility),
            LiquidityRule(min_daily_volume=cfg.min_liquidity),
            MinimumPriceRule(min_price=cfg.min_price),
            VolumeRatioRule(min_ratio=cfg.volume_dry_ratio),
        ],
        should_pass=[
            AdxTrendStrengthRule(min_adx=cfg.adx_min, max_adx=cfg.adx_max),
            AdxDirectionRule(),
            VolumeRatioRule(min_ratio=cfg.volume_above_avg_ratio),
            BollingerPositionRule(),
            MacdHistogramRule(),
            MfiThresholdRule(threshold=cfg.mfi_overbought),
            StochasticCrossRule(),
            AtrRangeRule(min_atr_pct=cfg.atr_min_pct, max_atr_pct=cfg.atr_max_pct),
        ],
        info_only=[
            GoldenCrossRule(max_cross_margin=cfg.golden_cross_margin),
            BollingerSqueezeRule(max_bandwidth=cfg.bollinger_squeeze_bandwidth),
            VolumeRatioRule(min_ratio=cfg.volume_breakout_ratio),
            ObvTrendRule(),
        ],
        entry_timing_must_pass=[
            PriceDropRule(max_drop_pct=cfg.max_drop_pct),
            IntradayMomentumRule(),
            VolumeConfirmationRule(min_volume_ratio=cfg.min_volume_confirmation),
            GapRule(max_gap_pct=cfg.max_gap_pct),
            IntradayRangeRule(max_range_position=cfg.max_intraday_range_position),
            ConsecutiveUpDaysRule(max_consecutive_up=cfg.max_consecutive_up_days),
        ],
    )


def create_moderate_policy(
    cfg: StrategyThresholds,
) -> TechnicalScreeningPolicy:
    """
    Moderate Strategy: Balanced approach.

    Expected: Win rate 50-60%, 5-10 trades/week, 2% risk/trade.
    """
    return TechnicalScreeningPolicy(
        setup_must_pass=[
            PriceAboveMaRule(MaPeriod.MA_20),
            MaAlignmentRule(MaPeriod.MA_20, MaPeriod.MA_60),
            MacdCrossRule(),
            RsiRangeRule(min_rsi=cfg.rsi_healthy_min),
        ],
        safety_must_pass=[
            RsiRangeRule(max_rsi=cfg.rsi_overbought),
            DailyRangeRule(max_daily_range_pct=cfg.max_daily_volatility),
            LiquidityRule(min_daily_volume=cfg.min_liquidity),
            MinimumPriceRule(min_price=cfg.min_price),
            VolumeRatioRule(min_ratio=cfg.volume_dry_ratio),
        ],
        should_pass=[
            PriceAboveMaRule(MaPeriod.MA_60),
            MacdPositiveRule(),
            AdxTrendStrengthRule(min_adx=cfg.adx_min, max_adx=cfg.adx_max),
            AdxDirectionRule(),
            StochasticThresholdRule(threshold=cfg.stoch_overbought),
            BollingerThresholdRule(max_percent_b=cfg.bollinger_max_pct_b),
            BollingerPositionRule(),
            VolumeRatioRule(min_ratio=cfg.volume_above_avg_ratio),
            MacdHistogramRule(),
            MfiThresholdRule(threshold=cfg.mfi_overbought),
            StochasticCrossRule(),
            AtrRangeRule(min_atr_pct=cfg.atr_min_pct, max_atr_pct=cfg.atr_max_pct),
        ],
        info_only=[
            RsiRangeRule(min_rsi=cfg.rsi_healthy_min, max_rsi=cfg.rsi_healthy_max),
            GoldenCrossRule(max_cross_margin=cfg.golden_cross_margin),
            BollingerSqueezeRule(max_bandwidth=cfg.bollinger_squeeze_bandwidth),
            VolumeRatioRule(min_ratio=cfg.volume_breakout_ratio),
            ObvTrendRule(),
        ],
        entry_timing_must_pass=[
            PriceDropRule(max_drop_pct=cfg.max_drop_pct),
            IntradayMomentumRule(),
            VolumeConfirmationRule(min_volume_ratio=cfg.min_volume_confirmation),
            ConsecutiveUpDaysRule(max_consecutive_up=cfg.max_consecutive_up_days),
        ],
    )


def create_aggressive_policy(
    cfg: StrategyThresholds,
) -> TechnicalScreeningPolicy:
    """
    Aggressive Strategy: More trades, lower win rate.

    Expected: Win rate 40-50%, 10-20 trades/week.
    WARNING: Requires excellent risk management!
    """
    return TechnicalScreeningPolicy(
        setup_must_pass=[
            PriceAboveMaRule(MaPeriod.MA_20),
            MacdCrossRule(),
        ],
        safety_must_pass=[
            RsiRangeRule(max_rsi=cfg.rsi_overbought),
            LiquidityRule(min_daily_volume=cfg.min_liquidity),
            MinimumPriceRule(min_price=cfg.min_price),
        ],
        should_pass=[
            MaAlignmentRule(MaPeriod.MA_20, MaPeriod.MA_60),
            PriceAboveMaRule(MaPeriod.MA_60),
            RsiRangeRule(min_rsi=cfg.rsi_healthy_min),
            MacdPositiveRule(),
            AdxTrendStrengthRule(min_adx=cfg.adx_min, max_adx=cfg.adx_max),
            DailyRangeRule(max_daily_range_pct=cfg.max_daily_volatility),
            VolumeRatioRule(min_ratio=cfg.volume_dry_ratio),
            StochasticThresholdRule(threshold=cfg.stoch_overbought),
            BollingerThresholdRule(max_percent_b=cfg.bollinger_max_pct_b),
            VolumeRatioRule(min_ratio=cfg.volume_above_avg_ratio),
            MacdHistogramRule(),
            MfiThresholdRule(threshold=cfg.mfi_overbought),
            AtrRangeRule(min_atr_pct=cfg.atr_min_pct, max_atr_pct=cfg.atr_max_pct),
        ],
        info_only=[
            AdxDirectionRule(),
            StochasticCrossRule(),
            BollingerPositionRule(),
            GoldenCrossRule(max_cross_margin=cfg.golden_cross_margin),
            BollingerSqueezeRule(max_bandwidth=cfg.bollinger_squeeze_bandwidth),
            VolumeRatioRule(min_ratio=cfg.volume_breakout_ratio),
            ObvTrendRule(),
        ],
        entry_timing_must_pass=[
            PriceDropRule(max_drop_pct=cfg.max_drop_pct),
            VolumeConfirmationRule(min_volume_ratio=cfg.min_volume_confirmation),
        ],
    )


def create_buzz_stock_policy(
    cfg: StrategyThresholds,
) -> TechnicalScreeningPolicy:
    """
    Buzz Stock Strategy: For social media trending stocks.

    Setup rules are empty — social buzz provides the setup.
    Only safety and timing matter.
    WARNING: Higher risk! Use strict stop loss.
    """
    return TechnicalScreeningPolicy(
        setup_must_pass=[],
        safety_must_pass=[
            RsiRangeRule(max_rsi=cfg.rsi_overbought),
            DailyRangeRule(max_daily_range_pct=cfg.max_daily_volatility),
            LiquidityRule(min_daily_volume=cfg.min_liquidity),
            MinimumPriceRule(min_price=cfg.min_price),
        ],
        should_pass=[
            PriceAboveMaRule(MaPeriod.MA_20),
            MacdCrossRule(),
            RsiRangeRule(min_rsi=cfg.rsi_healthy_min),
            AdxTrendStrengthRule(min_adx=cfg.adx_min, max_adx=cfg.adx_max),
            VolumeRatioRule(min_ratio=cfg.volume_above_avg_ratio),
            StochasticThresholdRule(threshold=cfg.stoch_overbought),
            BollingerThresholdRule(max_percent_b=cfg.bollinger_max_pct_b),
            MacdHistogramRule(),
            MfiThresholdRule(threshold=cfg.mfi_overbought),
            AtrRangeRule(min_atr_pct=cfg.atr_min_pct, max_atr_pct=cfg.atr_max_pct),
        ],
        info_only=[
            PriceAboveMaRule(MaPeriod.MA_60),
            MaAlignmentRule(MaPeriod.MA_20, MaPeriod.MA_60),
            MacdPositiveRule(),
            AdxDirectionRule(),
            StochasticCrossRule(),
            BollingerPositionRule(),
            GoldenCrossRule(max_cross_margin=cfg.golden_cross_margin),
            BollingerSqueezeRule(max_bandwidth=cfg.bollinger_squeeze_bandwidth),
            VolumeRatioRule(min_ratio=cfg.volume_breakout_ratio),
            ObvTrendRule(),
            VolumeRatioRule(min_ratio=cfg.volume_dry_ratio),
        ],
        entry_timing_must_pass=[
            PriceDropRule(max_drop_pct=cfg.max_drop_pct),
            IntradayMomentumRule(),
            VolumeConfirmationRule(min_volume_ratio=cfg.min_volume_confirmation),
        ],
    )


def create_nightly_screening_policy(
    cfg: StrategyThresholds,
) -> TechnicalScreeningPolicy:
    """
    Nightly Screening: For generating the technical watchlist.

    Runs after market close on historical data.
    No entry timing rules needed.
    Purpose: Find stocks with good setups for tomorrow.
    """
    return TechnicalScreeningPolicy(
        setup_must_pass=[
            PriceAboveMaRule(MaPeriod.MA_20),
            MaAlignmentRule(MaPeriod.MA_20, MaPeriod.MA_60),
            MacdCrossRule(),
            RsiRangeRule(min_rsi=cfg.rsi_healthy_min),
        ],
        safety_must_pass=[
            RsiRangeRule(max_rsi=cfg.rsi_overbought),
            LiquidityRule(min_daily_volume=cfg.min_liquidity),
            MinimumPriceRule(min_price=cfg.min_price),
            VolumeRatioRule(min_ratio=cfg.volume_above_avg_ratio),
        ],
        should_pass=[
            PriceAboveMaRule(MaPeriod.MA_60),
            MacdPositiveRule(),
            AdxTrendStrengthRule(min_adx=cfg.adx_min, max_adx=cfg.adx_max),
            AdxDirectionRule(),
            StochasticThresholdRule(threshold=cfg.stoch_overbought),
            BollingerThresholdRule(max_percent_b=cfg.bollinger_max_pct_b),
            BollingerPositionRule(),
            VolumeRatioRule(min_ratio=cfg.volume_dry_ratio),
            MacdHistogramRule(),
            MfiThresholdRule(threshold=cfg.mfi_overbought),
            StochasticCrossRule(),
            AtrRangeRule(min_atr_pct=cfg.atr_min_pct, max_atr_pct=cfg.atr_max_pct),
        ],
        info_only=[
            RsiRangeRule(min_rsi=cfg.rsi_healthy_min, max_rsi=cfg.rsi_healthy_max),
            GoldenCrossRule(max_cross_margin=cfg.golden_cross_margin),
            BollingerSqueezeRule(max_bandwidth=cfg.bollinger_squeeze_bandwidth),
            VolumeRatioRule(min_ratio=cfg.volume_breakout_ratio),
            ObvTrendRule(),
        ],
        entry_timing_must_pass=[],  # No entry timing for nightly
    )


def load_strategy_thresholds(
    strategies_path: Path,
    strategy_name: str,
) -> StrategyThresholds:
    """Load thresholds for a specific strategy from YAML."""
    raw = yaml.safe_load(strategies_path.read_text(encoding="utf-8"))
    strategy_data = raw["strategies"].get(strategy_name, {})
    return StrategyThresholds.model_validate(strategy_data)
