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
from a_domain.rules.process.indicators.momentum import MfiThresholdRule, RsiRangeRule
from a_domain.rules.process.indicators.trend import GoldenCrossRule, MaAlignmentRule, PriceAboveMaRule
from a_domain.rules.process.indicators.volatility import (
    BollingerPositionRule,
    BollingerSqueezeRule,
    BollingerThresholdRule,
)
from a_domain.rules.process.indicators.volume import LiquidityRule, MinimumPriceRule, ObvTrendRule, VolumeRatioRule
from a_domain.rules.technical.criteria.momentum import MacdBullishCriterion, StochasticHealthCriterion
from a_domain.rules.technical.criteria.trend import AdxTrendCriterion
from a_domain.rules.technical.criteria.volatility import VolatilitySafetyCriterion
from a_domain.rules.technical.policy import TechnicalScreeningPolicy
from a_domain.types.enums import MaPeriod, StrategyName
from b_application.schemas.config import StrategyThresholds


class TechnicalPolicyFactory:
    """
    Builds technical screening policies from strategy configuration.

    Use this factory when config or UI needs to dynamically enable,
    disable, or tune technical criteria.
    """

    def create(self, strategy_name: StrategyName, cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
        registry = {
            StrategyName.CONSERVATIVE: self.create_conservative,
            StrategyName.MODERATE: self.create_moderate,
            StrategyName.NIGHTLY: self.create_nightly,
            StrategyName.AGGRESSIVE: self.create_aggressive,
            StrategyName.BUZZ: self.create_buzz,
        }

        builder = registry.get(strategy_name, self.create_moderate)
        return builder(cfg)

    def create_conservative(self, cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
        return TechnicalScreeningPolicy(
            setup_must_pass=[
                PriceAboveMaRule(MaPeriod.MA_20),
                PriceAboveMaRule(MaPeriod.MA_60),
                MaAlignmentRule(MaPeriod.MA_20, MaPeriod.MA_60),
                MacdBullishCriterion(
                    require_cross=True,
                    require_positive=True,
                    require_histogram_positive=False,
                    allow_missing=False,
                ),
                RsiRangeRule(
                    min_rsi=cfg.rsi_healthy_min,
                    max_rsi=cfg.rsi_healthy_max,
                ),
            ],
            safety_must_pass=[
                RsiRangeRule(max_rsi=cfg.rsi_overbought),
                StochasticHealthCriterion(max_k=cfg.stoch_overbought),
                BollingerThresholdRule(max_percent_b=cfg.bollinger_max_pct_b),
                VolatilitySafetyCriterion(
                    max_daily_range_pct=cfg.max_daily_volatility,
                    min_atr_pct=None,
                    max_atr_pct=None,
                ),
                LiquidityRule(min_daily_volume=cfg.min_liquidity),
                MinimumPriceRule(min_price=cfg.min_price),
                VolumeRatioRule(min_ratio=cfg.volume_dry_ratio),
            ],
            should_pass=[
                AdxTrendCriterion(
                    min_adx=cfg.adx_min,
                    max_adx=cfg.adx_max,
                    require_direction=True,
                ),
                VolumeRatioRule(min_ratio=cfg.volume_above_avg_ratio),
                BollingerPositionRule(),
                MacdBullishCriterion(
                    require_cross=False,
                    require_positive=False,
                    require_histogram_positive=True,
                    allow_missing=True,
                ),
                MfiThresholdRule(threshold=cfg.mfi_overbought),
                StochasticHealthCriterion(
                    max_k=None,
                    require_cross=True,
                    allow_missing=True,
                ),
                VolatilitySafetyCriterion(
                    min_atr_pct=cfg.atr_min_pct,
                    max_atr_pct=cfg.atr_max_pct,
                    require_atr=False,
                ),
            ],
            info_only=[
                GoldenCrossRule(max_cross_margin=cfg.golden_cross_margin),
                BollingerSqueezeRule(max_bandwidth=cfg.bollinger_squeeze_bandwidth),
                VolumeRatioRule(min_ratio=cfg.volume_breakout_ratio),
                ObvTrendRule(),
            ],
            entry_timing_must_pass=self._entry_timing_criteria(cfg),
        )

    def create_moderate(self, cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
        return TechnicalScreeningPolicy(
            setup_must_pass=[
                PriceAboveMaRule(MaPeriod.MA_20),
                MaAlignmentRule(MaPeriod.MA_20, MaPeriod.MA_60),
                MacdBullishCriterion(
                    require_cross=True,
                    require_positive=False,
                    require_histogram_positive=False,
                    allow_missing=False,
                ),
                RsiRangeRule(min_rsi=cfg.rsi_healthy_min),
            ],
            safety_must_pass=[
                RsiRangeRule(max_rsi=cfg.rsi_overbought),
                VolatilitySafetyCriterion(max_daily_range_pct=cfg.max_daily_volatility),
                LiquidityRule(min_daily_volume=cfg.min_liquidity),
                MinimumPriceRule(min_price=cfg.min_price),
                VolumeRatioRule(min_ratio=cfg.volume_dry_ratio),
            ],
            should_pass=[
                PriceAboveMaRule(MaPeriod.MA_60),
                MacdBullishCriterion(
                    require_cross=False,
                    require_positive=True,
                    require_histogram_positive=True,
                    allow_missing=True,
                ),
                AdxTrendCriterion(
                    min_adx=cfg.adx_min,
                    max_adx=cfg.adx_max,
                    require_direction=True,
                ),
                StochasticHealthCriterion(
                    max_k=cfg.stoch_overbought,
                    require_cross=True,
                    allow_missing=True,
                ),
                BollingerThresholdRule(max_percent_b=cfg.bollinger_max_pct_b),
                BollingerPositionRule(),
                VolumeRatioRule(min_ratio=cfg.volume_above_avg_ratio),
                MfiThresholdRule(threshold=cfg.mfi_overbought),
                VolatilitySafetyCriterion(
                    min_atr_pct=cfg.atr_min_pct,
                    max_atr_pct=cfg.atr_max_pct,
                    require_atr=False,
                ),
            ],
            info_only=[
                RsiRangeRule(
                    min_rsi=cfg.rsi_healthy_min,
                    max_rsi=cfg.rsi_healthy_max,
                ),
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

    def create_nightly(self, cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
        return TechnicalScreeningPolicy(
            setup_must_pass=[
                PriceAboveMaRule(MaPeriod.MA_20),
                MaAlignmentRule(MaPeriod.MA_20, MaPeriod.MA_60),
                MacdBullishCriterion(
                    require_cross=True,
                    require_positive=False,
                    require_histogram_positive=False,
                    allow_missing=False,
                ),
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
                MacdBullishCriterion(
                    require_cross=False,
                    require_positive=True,
                    require_histogram_positive=True,
                    allow_missing=True,
                ),
                AdxTrendCriterion(
                    min_adx=cfg.adx_min,
                    max_adx=cfg.adx_max,
                    require_direction=True,
                ),
                StochasticHealthCriterion(
                    max_k=cfg.stoch_overbought,
                    require_cross=True,
                    allow_missing=True,
                ),
                BollingerThresholdRule(max_percent_b=cfg.bollinger_max_pct_b),
                BollingerPositionRule(),
                VolumeRatioRule(min_ratio=cfg.volume_dry_ratio),
                MfiThresholdRule(threshold=cfg.mfi_overbought),
                VolatilitySafetyCriterion(
                    min_atr_pct=cfg.atr_min_pct,
                    max_atr_pct=cfg.atr_max_pct,
                    require_atr=False,
                ),
            ],
            info_only=[
                RsiRangeRule(
                    min_rsi=cfg.rsi_healthy_min,
                    max_rsi=cfg.rsi_healthy_max,
                ),
                GoldenCrossRule(max_cross_margin=cfg.golden_cross_margin),
                BollingerSqueezeRule(max_bandwidth=cfg.bollinger_squeeze_bandwidth),
                VolumeRatioRule(min_ratio=cfg.volume_breakout_ratio),
                ObvTrendRule(),
            ],
            entry_timing_must_pass=[],
        )

    def create_aggressive(self, cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
        policy = self.create_moderate(cfg)

        return TechnicalScreeningPolicy(
            setup_must_pass=[
                PriceAboveMaRule(MaPeriod.MA_20),
                MacdBullishCriterion(
                    require_cross=True,
                    require_positive=False,
                    require_histogram_positive=False,
                    allow_missing=False,
                ),
            ],
            safety_must_pass=policy.safety_must_pass,
            should_pass=policy.should_pass,
            info_only=policy.info_only,
            entry_timing_must_pass=policy.entry_timing_must_pass,
        )

    def create_buzz(self, cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
        policy = self.create_moderate(cfg)

        return TechnicalScreeningPolicy(
            setup_must_pass=[
                MinimumPriceRule(min_price=cfg.min_price),
                LiquidityRule(min_daily_volume=cfg.min_liquidity),
            ],
            safety_must_pass=policy.safety_must_pass,
            should_pass=[
                VolumeRatioRule(min_ratio=cfg.volume_above_avg_ratio),
                MacdBullishCriterion(
                    require_cross=False,
                    require_positive=False,
                    require_histogram_positive=True,
                    allow_missing=True,
                ),
                StochasticHealthCriterion(
                    max_k=cfg.stoch_overbought,
                    require_cross=False,
                    allow_missing=True,
                ),
            ],
            info_only=policy.info_only,
            entry_timing_must_pass=policy.entry_timing_must_pass,
        )

    def _entry_timing_criteria(self, cfg: StrategyThresholds):
        return [
            PriceDropRule(max_drop_pct=cfg.max_drop_pct),
            IntradayMomentumRule(),
            VolumeConfirmationRule(min_volume_ratio=cfg.min_volume_confirmation),
            GapRule(max_gap_pct=cfg.max_gap_pct),
            IntradayRangeRule(max_range_position=cfg.max_intraday_range_position),
            ConsecutiveUpDaysRule(max_consecutive_up=cfg.max_consecutive_up_days),
        ]


def create_policy_from_config(
    strategy_name: StrategyName,
    cfg: StrategyThresholds,
) -> TechnicalScreeningPolicy:
    return TechnicalPolicyFactory().create(strategy_name, cfg)


def create_conservative_policy(cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
    return TechnicalPolicyFactory().create_conservative(cfg)


def create_moderate_policy(cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
    return TechnicalPolicyFactory().create_moderate(cfg)


def create_nightly_screening_policy(cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
    return TechnicalPolicyFactory().create_nightly(cfg)


def load_strategy_thresholds(
    strategies_path: Path,
    strategy_name: StrategyName,
) -> StrategyThresholds:
    raw = yaml.safe_load(strategies_path.read_text(encoding="utf-8"))
    strategy_data = raw.get("strategies", {}).get(strategy_name.value, {})

    return StrategyThresholds.model_validate(strategy_data)
