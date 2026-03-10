"""
Screening Policy Factory.

Application layer: decides WHICH rules go in WHICH tier.
All threshold values injected via StrategyThresholds.
"""
from pathlib import Path

import yaml

from a_domain.rules.process.indicators.entry_timing import (
    ConsecutiveUpDaysRule,
    GapRule,
    IntradayMomentumRule,
    IntradayRangeRule,
    PriceDropRule,
    VolumeConfirmationRule,
)
from a_domain.rules.process.indicators.momentum import (
    MacdCrossRule,
    MacdHistogramRule,
    MacdPositiveRule,
    MfiThresholdRule,
    RsiRangeRule,
    StochasticCrossRule,
    StochasticThresholdRule,
)
from a_domain.rules.process.indicators.trend import (
    AdxDirectionRule,
    AdxTrendStrengthRule,
    GoldenCrossRule,
    MaAlignmentRule,
    PriceAboveMaRule,
)
from a_domain.rules.process.indicators.volatility import (
    AtrRangeRule,
    BollingerPositionRule,
    BollingerSqueezeRule,
    BollingerThresholdRule,
    DailyRangeRule,
)
from a_domain.rules.process.indicators.volume import (
    LiquidityRule,
    MinimumPriceRule,
    ObvTrendRule,
    VolumeRatioRule,
)
from a_domain.rules.process.policies import TechnicalScreeningPolicy
from a_domain.types.enums import MaPeriod
from b_application.schemas.config import StrategyThresholds


def create_conservative_policy(cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
    return TechnicalScreeningPolicy(
        setup_must_pass=[
            PriceAboveMaRule(MaPeriod.MA_20), PriceAboveMaRule(MaPeriod.MA_60),
            MaAlignmentRule(MaPeriod.MA_20, MaPeriod.MA_60),
            MacdCrossRule(), MacdPositiveRule(),
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
            AdxDirectionRule(), VolumeRatioRule(min_ratio=cfg.volume_above_avg_ratio),
            BollingerPositionRule(), MacdHistogramRule(),
            MfiThresholdRule(threshold=cfg.mfi_overbought), StochasticCrossRule(),
            AtrRangeRule(min_atr_pct=cfg.atr_min_pct, max_atr_pct=cfg.atr_max_pct),
        ],
        info_only=[
            GoldenCrossRule(max_cross_margin=cfg.golden_cross_margin),
            BollingerSqueezeRule(max_bandwidth=cfg.bollinger_squeeze_bandwidth),
            VolumeRatioRule(min_ratio=cfg.volume_breakout_ratio), ObvTrendRule(),
        ],
        entry_timing_must_pass=[
            PriceDropRule(max_drop_pct=cfg.max_drop_pct), IntradayMomentumRule(),
            VolumeConfirmationRule(min_volume_ratio=cfg.min_volume_confirmation),
            GapRule(max_gap_pct=cfg.max_gap_pct),
            IntradayRangeRule(max_range_position=cfg.max_intraday_range_position),
            ConsecutiveUpDaysRule(max_consecutive_up=cfg.max_consecutive_up_days),
        ],
    )


def create_moderate_policy(cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
    return TechnicalScreeningPolicy(
        setup_must_pass=[
            PriceAboveMaRule(MaPeriod.MA_20),
            MaAlignmentRule(MaPeriod.MA_20, MaPeriod.MA_60),
            MacdCrossRule(), RsiRangeRule(min_rsi=cfg.rsi_healthy_min),
        ],
        safety_must_pass=[
            RsiRangeRule(max_rsi=cfg.rsi_overbought),
            DailyRangeRule(max_daily_range_pct=cfg.max_daily_volatility),
            LiquidityRule(min_daily_volume=cfg.min_liquidity),
            MinimumPriceRule(min_price=cfg.min_price),
            VolumeRatioRule(min_ratio=cfg.volume_dry_ratio),
        ],
        should_pass=[
            PriceAboveMaRule(MaPeriod.MA_60), MacdPositiveRule(),
            AdxTrendStrengthRule(min_adx=cfg.adx_min, max_adx=cfg.adx_max),
            AdxDirectionRule(), StochasticThresholdRule(threshold=cfg.stoch_overbought),
            BollingerThresholdRule(max_percent_b=cfg.bollinger_max_pct_b),
            BollingerPositionRule(), VolumeRatioRule(min_ratio=cfg.volume_above_avg_ratio),
            MacdHistogramRule(), MfiThresholdRule(threshold=cfg.mfi_overbought),
            StochasticCrossRule(),
            AtrRangeRule(min_atr_pct=cfg.atr_min_pct, max_atr_pct=cfg.atr_max_pct),
        ],
        info_only=[
            RsiRangeRule(min_rsi=cfg.rsi_healthy_min, max_rsi=cfg.rsi_healthy_max),
            GoldenCrossRule(max_cross_margin=cfg.golden_cross_margin),
            BollingerSqueezeRule(max_bandwidth=cfg.bollinger_squeeze_bandwidth),
            VolumeRatioRule(min_ratio=cfg.volume_breakout_ratio), ObvTrendRule(),
        ],
        entry_timing_must_pass=[
            PriceDropRule(max_drop_pct=cfg.max_drop_pct), IntradayMomentumRule(),
            VolumeConfirmationRule(min_volume_ratio=cfg.min_volume_confirmation),
            ConsecutiveUpDaysRule(max_consecutive_up=cfg.max_consecutive_up_days),
        ],
    )


def create_nightly_screening_policy(cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
    """Nightly: No entry timing rules. Find stocks with good setups for tomorrow."""
    return TechnicalScreeningPolicy(
        setup_must_pass=[
            PriceAboveMaRule(MaPeriod.MA_20),
            MaAlignmentRule(MaPeriod.MA_20, MaPeriod.MA_60),
            MacdCrossRule(), RsiRangeRule(min_rsi=cfg.rsi_healthy_min),
        ],
        safety_must_pass=[
            RsiRangeRule(max_rsi=cfg.rsi_overbought),
            LiquidityRule(min_daily_volume=cfg.min_liquidity),
            MinimumPriceRule(min_price=cfg.min_price),
            VolumeRatioRule(min_ratio=cfg.volume_above_avg_ratio),
        ],
        should_pass=[
            PriceAboveMaRule(MaPeriod.MA_60), MacdPositiveRule(),
            AdxTrendStrengthRule(min_adx=cfg.adx_min, max_adx=cfg.adx_max),
            AdxDirectionRule(), StochasticThresholdRule(threshold=cfg.stoch_overbought),
            BollingerThresholdRule(max_percent_b=cfg.bollinger_max_pct_b),
            BollingerPositionRule(), VolumeRatioRule(min_ratio=cfg.volume_dry_ratio),
            MacdHistogramRule(), MfiThresholdRule(threshold=cfg.mfi_overbought),
            StochasticCrossRule(),
            AtrRangeRule(min_atr_pct=cfg.atr_min_pct, max_atr_pct=cfg.atr_max_pct),
        ],
        info_only=[
            RsiRangeRule(min_rsi=cfg.rsi_healthy_min, max_rsi=cfg.rsi_healthy_max),
            GoldenCrossRule(max_cross_margin=cfg.golden_cross_margin),
            BollingerSqueezeRule(max_bandwidth=cfg.bollinger_squeeze_bandwidth),
            VolumeRatioRule(min_ratio=cfg.volume_breakout_ratio), ObvTrendRule(),
        ],
        entry_timing_must_pass=[],
    )


def load_strategy_thresholds(strategies_path: Path, strategy_name: str) -> StrategyThresholds:
    raw = yaml.safe_load(strategies_path.read_text(encoding="utf-8"))
    strategy_data = raw["strategies"].get(strategy_name, {})
    return StrategyThresholds.model_validate(strategy_data)
