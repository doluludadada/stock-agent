from pathlib import Path

import yaml

from a_domain.rules.technical.criteria.momentum import (
    MacdBullishCriterion,
    MfiThresholdCriterion,
    RsiRangeCriterion,
    StochasticHealthCriterion,
)
from a_domain.rules.technical.criteria.timing import (
    ConsecutiveUpDaysCriterion,
    GapCriterion,
    IntradayMomentumCriterion,
    IntradayRangeCriterion,
    IntradayVolumeConfirmationCriterion,
    PriceDropCriterion,
)
from a_domain.rules.technical.criteria.trend import (
    AdxTrendCriterion,
    GoldenCrossCriterion,
    MaAlignmentCriterion,
    PriceAboveMaCriterion,
)
from a_domain.rules.technical.criteria.volatility import (
    BollingerPositionCriterion,
    BollingerSqueezeCriterion,
    BollingerThresholdCriterion,
    VolatilitySafetyCriterion,
)
from a_domain.rules.technical.criteria.volume import (
    LiquidityCriterion,
    MinimumPriceCriterion,
    ObvTrendCriterion,
    VolumeExpansionCriterion,
)
from a_domain.rules.technical.policy import TechnicalScreeningPolicy
from a_domain.types.enums import StrategyName
from b_application.schemas.config import StrategyThresholds


class TechnicalPolicyFactory:
    def create(
        self,
        strategy_name: StrategyName,
        cfg: StrategyThresholds,
    ) -> TechnicalScreeningPolicy:
        match strategy_name:
            case StrategyName.CONSERVATIVE:
                return self.create_conservative(cfg)

            case StrategyName.AGGRESSIVE:
                return self.create_aggressive(cfg)

            case StrategyName.BUZZ:
                return self.create_buzz(cfg)

            case StrategyName.NIGHTLY:
                return self.create_nightly(cfg)

            case _:
                return self.create_moderate(cfg)

    def create_conservative(self, cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
        return TechnicalScreeningPolicy(
            setup_must_pass=[
                PriceAboveMaCriterion(20),
                PriceAboveMaCriterion(60),
                MaAlignmentCriterion(20, 60),
                MacdBullishCriterion(
                    require_cross=True,
                    require_positive=True,
                    require_histogram_positive=False,
                    allow_missing=False,
                ),
                RsiRangeCriterion(
                    min_rsi=cfg.rsi_healthy_min,
                    max_rsi=cfg.rsi_healthy_max,
                ),
            ],
            safety_must_pass=[
                RsiRangeCriterion(max_rsi=cfg.rsi_overbought),
                StochasticHealthCriterion(max_k=cfg.stoch_overbought),
                BollingerThresholdCriterion(max_percent_b=cfg.bollinger_max_pct_b),
                VolatilitySafetyCriterion(max_daily_range_pct=cfg.max_daily_volatility),
                LiquidityCriterion(min_daily_volume=cfg.min_liquidity),
                MinimumPriceCriterion(min_price=cfg.min_price),
                VolumeExpansionCriterion(min_ratio=cfg.volume_dry_ratio),
            ],
            should_pass=[
                AdxTrendCriterion(
                    min_adx=cfg.adx_min,
                    max_adx=cfg.adx_max,
                    require_direction=True,
                ),
                VolumeExpansionCriterion(min_ratio=cfg.volume_above_avg_ratio),
                BollingerPositionCriterion(),
                MacdBullishCriterion(
                    require_cross=False,
                    require_positive=False,
                    require_histogram_positive=True,
                    allow_missing=True,
                ),
                MfiThresholdCriterion(max_mfi=cfg.mfi_overbought),
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
                GoldenCrossCriterion(max_cross_margin=cfg.golden_cross_margin),
                BollingerSqueezeCriterion(max_bandwidth=cfg.bollinger_squeeze_bandwidth),
                VolumeExpansionCriterion(min_ratio=cfg.volume_breakout_ratio),
                ObvTrendCriterion(),
            ],
            entry_timing_must_pass=self._entry_timing_criteria(cfg),
        )

    def create_moderate(self, cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
        return TechnicalScreeningPolicy(
            setup_must_pass=[
                PriceAboveMaCriterion(20),
                MaAlignmentCriterion(20, 60),
                MacdBullishCriterion(
                    require_cross=True,
                    require_positive=False,
                    require_histogram_positive=False,
                    allow_missing=False,
                ),
                RsiRangeCriterion(min_rsi=cfg.rsi_healthy_min),
            ],
            safety_must_pass=[
                RsiRangeCriterion(max_rsi=cfg.rsi_overbought),
                VolatilitySafetyCriterion(max_daily_range_pct=cfg.max_daily_volatility),
                LiquidityCriterion(min_daily_volume=cfg.min_liquidity),
                MinimumPriceCriterion(min_price=cfg.min_price),
                VolumeExpansionCriterion(min_ratio=cfg.volume_dry_ratio),
            ],
            should_pass=[
                PriceAboveMaCriterion(60),
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
                BollingerThresholdCriterion(max_percent_b=cfg.bollinger_max_pct_b),
                BollingerPositionCriterion(),
                VolumeExpansionCriterion(min_ratio=cfg.volume_above_avg_ratio),
                MfiThresholdCriterion(max_mfi=cfg.mfi_overbought),
                VolatilitySafetyCriterion(
                    min_atr_pct=cfg.atr_min_pct,
                    max_atr_pct=cfg.atr_max_pct,
                    require_atr=False,
                ),
            ],
            info_only=[
                RsiRangeCriterion(
                    min_rsi=cfg.rsi_healthy_min,
                    max_rsi=cfg.rsi_healthy_max,
                ),
                GoldenCrossCriterion(max_cross_margin=cfg.golden_cross_margin),
                BollingerSqueezeCriterion(max_bandwidth=cfg.bollinger_squeeze_bandwidth),
                VolumeExpansionCriterion(min_ratio=cfg.volume_breakout_ratio),
                ObvTrendCriterion(),
            ],
            entry_timing_must_pass=[
                PriceDropCriterion(max_drop_pct=cfg.max_drop_pct),
                IntradayMomentumCriterion(),
                IntradayVolumeConfirmationCriterion(min_volume_ratio=cfg.min_volume_confirmation),
                ConsecutiveUpDaysCriterion(max_consecutive_up=cfg.max_consecutive_up_days),
            ],
        )

    def create_nightly(self, cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
        return TechnicalScreeningPolicy(
            setup_must_pass=[
                PriceAboveMaCriterion(20),
                MaAlignmentCriterion(20, 60),
                MacdBullishCriterion(
                    require_cross=True,
                    require_positive=False,
                    require_histogram_positive=False,
                    allow_missing=False,
                ),
                RsiRangeCriterion(min_rsi=cfg.rsi_healthy_min),
            ],
            safety_must_pass=[
                RsiRangeCriterion(max_rsi=cfg.rsi_overbought),
                LiquidityCriterion(min_daily_volume=cfg.min_liquidity),
                MinimumPriceCriterion(min_price=cfg.min_price),
                VolumeExpansionCriterion(min_ratio=cfg.volume_above_avg_ratio),
            ],
            should_pass=[
                PriceAboveMaCriterion(60),
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
                BollingerThresholdCriterion(max_percent_b=cfg.bollinger_max_pct_b),
                BollingerPositionCriterion(),
                VolumeExpansionCriterion(min_ratio=cfg.volume_dry_ratio),
                MfiThresholdCriterion(max_mfi=cfg.mfi_overbought),
                VolatilitySafetyCriterion(
                    min_atr_pct=cfg.atr_min_pct,
                    max_atr_pct=cfg.atr_max_pct,
                    require_atr=False,
                ),
            ],
            info_only=[
                RsiRangeCriterion(
                    min_rsi=cfg.rsi_healthy_min,
                    max_rsi=cfg.rsi_healthy_max,
                ),
                GoldenCrossCriterion(max_cross_margin=cfg.golden_cross_margin),
                BollingerSqueezeCriterion(max_bandwidth=cfg.bollinger_squeeze_bandwidth),
                VolumeExpansionCriterion(min_ratio=cfg.volume_breakout_ratio),
                ObvTrendCriterion(),
            ],
            entry_timing_must_pass=[],
        )

    def create_aggressive(self, cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
        moderate = self.create_moderate(cfg)

        return TechnicalScreeningPolicy(
            setup_must_pass=[
                PriceAboveMaCriterion(20),
                MacdBullishCriterion(
                    require_cross=True,
                    require_positive=False,
                    require_histogram_positive=False,
                    allow_missing=False,
                ),
            ],
            safety_must_pass=moderate.safety_must_pass,
            should_pass=moderate.should_pass,
            info_only=moderate.info_only,
            entry_timing_must_pass=moderate.entry_timing_must_pass,
        )

    def create_buzz(self, cfg: StrategyThresholds) -> TechnicalScreeningPolicy:
        moderate = self.create_moderate(cfg)

        return TechnicalScreeningPolicy(
            setup_must_pass=[
                MinimumPriceCriterion(min_price=cfg.min_price),
                LiquidityCriterion(min_daily_volume=cfg.min_liquidity),
            ],
            safety_must_pass=moderate.safety_must_pass,
            should_pass=[
                VolumeExpansionCriterion(min_ratio=cfg.volume_above_avg_ratio),
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
            info_only=moderate.info_only,
            entry_timing_must_pass=moderate.entry_timing_must_pass,
        )

    def _entry_timing_criteria(self, cfg: StrategyThresholds):
        return [
            PriceDropCriterion(max_drop_pct=cfg.max_drop_pct),
            IntradayMomentumCriterion(),
            IntradayVolumeConfirmationCriterion(min_volume_ratio=cfg.min_volume_confirmation),
            GapCriterion(max_gap_pct=cfg.max_gap_pct),
            IntradayRangeCriterion(max_range_position=cfg.max_intraday_range_position),
            ConsecutiveUpDaysCriterion(max_consecutive_up=cfg.max_consecutive_up_days),
        ]


def create_policy_from_config(
    strategy_name: StrategyName,
    cfg: StrategyThresholds,
) -> TechnicalScreeningPolicy:
    return TechnicalPolicyFactory().create(strategy_name, cfg)


def load_strategy_thresholds(
    strategies_path: Path,
    strategy_name: StrategyName,
) -> StrategyThresholds:
    raw = yaml.safe_load(strategies_path.read_text(encoding="utf-8"))
    strategy_data = raw.get("strategies", {}).get(strategy_name.value, {})

    return StrategyThresholds.model_validate(strategy_data)
