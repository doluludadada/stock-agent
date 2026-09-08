# backend/src/b_application/factories/technical_strategy.py

from a_domain.rules.technical.calculation.parameters import IndicatorParameters
from a_domain.rules.technical.criteria.base import TechnicalCriterion
from a_domain.rules.technical.criteria.momentum import (
    MacdBullishCriterion,
    MfiThresholdCriterion,
    RsiRangeCriterion,
    StochasticHealthCriterion,
)
from a_domain.rules.technical.criteria.trend import (
    AdxTrendCriterion,
    GoldenCrossCriterion,
    MaAlignmentCriterion,
    PriceAboveMaCriterion,
)
from a_domain.rules.technical.criteria.volatility import (
    AtrRangeCriterion,
    BollingerPositionCriterion,
    BollingerSqueezeCriterion,
    BollingerThresholdCriterion,
    DailyRangeCriterion,
)
from a_domain.rules.technical.criteria.volume import (
    LiquidityCriterion,
    MinimumPriceCriterion,
    ObvTrendCriterion,
    VolumeExpansionCriterion,
)
from a_domain.rules.technical.strategy import TechnicalStrategy
from a_domain.types.enums import StrategyName
from b_application.schemas.config import (
    AppConfig,
    ScoringConfig,
    StrategyThresholds,
)
from b_application.schemas.technical_strategies import TechnicalStrategies


# TODO(US-304):
# Make technical criterion composition configurable from validated UI/config.
# Keep explicit criterion construction here until that story is implemented.
class TechnicalStrategyFactory:
    def create(
        self,
        strategy_name: StrategyName,
        thresholds: StrategyThresholds,
        scoring: ScoringConfig,
        indicators: IndicatorParameters,
    ) -> TechnicalStrategy:
        match strategy_name:
            case StrategyName.CONSERVATIVE:
                return self.create_conservative(thresholds, scoring, indicators)

            case StrategyName.MODERATE:
                return self.create_moderate(thresholds, scoring, indicators)

            case StrategyName.AGGRESSIVE:
                return self.create_aggressive(thresholds, scoring, indicators)

            case StrategyName.BUZZ:
                return self.create_buzz(thresholds, scoring)

            case StrategyName.NIGHTLY:
                return self.create_nightly(thresholds, scoring, indicators)

        raise ValueError(f"Unsupported technical strategy: {strategy_name}")

    def create_conservative(
        self,
        thresholds: StrategyThresholds,
        scoring: ScoringConfig,
        indicators: IndicatorParameters,
    ) -> TechnicalStrategy:
        return self._build_strategy(
            must_pass=self._conservative_must_pass(thresholds, indicators),
            should_pass=self._conservative_should_pass(thresholds),
            observations=self.create_observations(thresholds),
            scoring=scoring,
        )

    def create_moderate(
        self,
        thresholds: StrategyThresholds,
        scoring: ScoringConfig,
        indicators: IndicatorParameters,
    ) -> TechnicalStrategy:
        return self._build_strategy(
            must_pass=self._moderate_must_pass(thresholds, indicators),
            should_pass=self._moderate_should_pass(thresholds, indicators),
            observations=self.create_observations(thresholds),
            scoring=scoring,
        )

    def create_aggressive(
        self,
        thresholds: StrategyThresholds,
        scoring: ScoringConfig,
        indicators: IndicatorParameters,
    ) -> TechnicalStrategy:
        return self._build_strategy(
            must_pass=self._aggressive_must_pass(thresholds, indicators),
            should_pass=self._aggressive_should_pass(thresholds, indicators),
            observations=self.create_observations(thresholds),
            scoring=scoring,
        )

    def create_buzz(
        self,
        thresholds: StrategyThresholds,
        scoring: ScoringConfig,
    ) -> TechnicalStrategy:
        return self._build_strategy(
            must_pass=self._buzz_must_pass(thresholds),
            should_pass=self._buzz_should_pass(thresholds),
            observations=self.create_observations(thresholds),
            scoring=scoring,
        )

    def create_nightly(
        self,
        thresholds: StrategyThresholds,
        scoring: ScoringConfig,
        indicators: IndicatorParameters,
    ) -> TechnicalStrategy:
        return self._build_strategy(
            must_pass=self._nightly_must_pass(thresholds, indicators),
            should_pass=self._nightly_should_pass(thresholds, indicators),
            observations=self.create_observations(thresholds),
            scoring=scoring,
        )

    def create_observations(
        self,
        thresholds: StrategyThresholds,
    ) -> list[TechnicalCriterion]:
        return [
            RsiRangeCriterion(
                thresholds.rsi_healthy_min,
                thresholds.rsi_healthy_max,
            ),
            GoldenCrossCriterion(
                max_cross_margin=thresholds.golden_cross_margin,
            ),
            BollingerSqueezeCriterion(
                thresholds.bollinger_squeeze_bandwidth,
            ),
            VolumeExpansionCriterion(
                thresholds.volume_breakout_ratio,
            ),
            ObvTrendCriterion(),
        ]

    def _build_strategy(
        self,
        must_pass: list[TechnicalCriterion],
        should_pass: list[TechnicalCriterion],
        observations: list[TechnicalCriterion],
        scoring: ScoringConfig,
    ) -> TechnicalStrategy:
        return TechnicalStrategy(
            must_pass=must_pass,
            should_pass=should_pass,
            observe=observations,
            base_score=scoring.base,
            hard_failure_penalty=scoring.hard_failure_penalty,
            soft_failure_penalty=scoring.soft_failure_penalty,
            observation_bonus=scoring.observation_bonus,
        )

    def _conservative_must_pass(
        self,
        thresholds: StrategyThresholds,
        indicators: IndicatorParameters,
    ) -> list[TechnicalCriterion]:
        return [
            PriceAboveMaCriterion(indicators.ma_mid),
            PriceAboveMaCriterion(indicators.ma_long),
            MaAlignmentCriterion(
                indicators.ma_mid,
                indicators.ma_long,
            ),
            MacdBullishCriterion(
                require_above_signal=True,
                require_positive=True,
            ),
            RsiRangeCriterion(
                thresholds.rsi_healthy_min,
                thresholds.rsi_healthy_max,
            ),
            StochasticHealthCriterion(
                max_k=thresholds.stoch_overbought,
            ),
            BollingerThresholdCriterion(
                thresholds.bollinger_max_pct_b,
            ),
            DailyRangeCriterion(
                thresholds.max_daily_volatility,
            ),
            LiquidityCriterion(
                thresholds.min_liquidity,
            ),
            MinimumPriceCriterion(
                thresholds.min_price,
            ),
            VolumeExpansionCriterion(
                thresholds.volume_dry_ratio,
            ),
        ]

    def _conservative_should_pass(
        self,
        thresholds: StrategyThresholds,
    ) -> list[TechnicalCriterion]:
        return [
            AdxTrendCriterion(
                thresholds.adx_min,
                thresholds.adx_max,
                require_direction=True,
            ),
            VolumeExpansionCriterion(
                thresholds.volume_above_avg_ratio,
            ),
            BollingerPositionCriterion(),
            MacdBullishCriterion(
                require_above_signal=False,
                require_histogram_positive=True,
            ),
            MfiThresholdCriterion(
                thresholds.mfi_overbought,
            ),
            StochasticHealthCriterion(
                max_k=None,
                require_k_above_d=True,
            ),
            AtrRangeCriterion(
                thresholds.atr_min_pct,
                thresholds.atr_max_pct,
            ),
        ]

    def _moderate_must_pass(
        self,
        thresholds: StrategyThresholds,
        indicators: IndicatorParameters,
    ) -> list[TechnicalCriterion]:
        return [
            PriceAboveMaCriterion(indicators.ma_mid),
            MaAlignmentCriterion(
                indicators.ma_mid,
                indicators.ma_long,
            ),
            MacdBullishCriterion(
                require_above_signal=True,
            ),
            RsiRangeCriterion(
                min_rsi=thresholds.rsi_healthy_min,
            ),
            RsiRangeCriterion(
                max_rsi=thresholds.rsi_overbought,
            ),
            DailyRangeCriterion(
                thresholds.max_daily_volatility,
            ),
            LiquidityCriterion(
                thresholds.min_liquidity,
            ),
            MinimumPriceCriterion(
                thresholds.min_price,
            ),
            VolumeExpansionCriterion(
                thresholds.volume_dry_ratio,
            ),
        ]

    def _moderate_should_pass(
        self,
        thresholds: StrategyThresholds,
        indicators: IndicatorParameters,
    ) -> list[TechnicalCriterion]:
        return [
            PriceAboveMaCriterion(indicators.ma_long),
            MacdBullishCriterion(
                require_above_signal=False,
                require_positive=True,
                require_histogram_positive=True,
            ),
            AdxTrendCriterion(
                thresholds.adx_min,
                thresholds.adx_max,
                require_direction=True,
            ),
            StochasticHealthCriterion(
                max_k=thresholds.stoch_overbought,
                require_k_above_d=True,
            ),
            BollingerThresholdCriterion(
                thresholds.bollinger_max_pct_b,
            ),
            BollingerPositionCriterion(),
            VolumeExpansionCriterion(
                thresholds.volume_above_avg_ratio,
            ),
            MfiThresholdCriterion(
                thresholds.mfi_overbought,
            ),
            AtrRangeCriterion(
                thresholds.atr_min_pct,
                thresholds.atr_max_pct,
            ),
        ]

    def _aggressive_must_pass(
        self,
        thresholds: StrategyThresholds,
        indicators: IndicatorParameters,
    ) -> list[TechnicalCriterion]:
        return [
            PriceAboveMaCriterion(
                indicators.ma_mid,
            ),
            MacdBullishCriterion(
                require_above_signal=True,
            ),
            RsiRangeCriterion(
                max_rsi=thresholds.rsi_overbought,
            ),
            DailyRangeCriterion(
                thresholds.max_daily_volatility,
            ),
            LiquidityCriterion(
                thresholds.min_liquidity,
            ),
            MinimumPriceCriterion(
                thresholds.min_price,
            ),
            VolumeExpansionCriterion(
                thresholds.volume_dry_ratio,
            ),
        ]

    def _aggressive_should_pass(
        self,
        thresholds: StrategyThresholds,
        indicators: IndicatorParameters,
    ) -> list[TechnicalCriterion]:
        return [
            PriceAboveMaCriterion(
                indicators.ma_long,
            ),
            MacdBullishCriterion(
                require_above_signal=False,
                require_positive=True,
                require_histogram_positive=True,
            ),
            AdxTrendCriterion(
                thresholds.adx_min,
                thresholds.adx_max,
                require_direction=True,
            ),
            StochasticHealthCriterion(
                max_k=thresholds.stoch_overbought,
                require_k_above_d=True,
            ),
            BollingerThresholdCriterion(
                thresholds.bollinger_max_pct_b,
            ),
            VolumeExpansionCriterion(
                thresholds.volume_above_avg_ratio,
            ),
            MfiThresholdCriterion(
                thresholds.mfi_overbought,
            ),
            AtrRangeCriterion(
                thresholds.atr_min_pct,
                thresholds.atr_max_pct,
            ),
        ]

    def _buzz_must_pass(
        self,
        thresholds: StrategyThresholds,
    ) -> list[TechnicalCriterion]:
        # Buzz is a short-term momentum workflow.
        # Only tradeability and extreme volatility stay as hard gates.
        return [
            MinimumPriceCriterion(
                thresholds.min_price,
            ),
            LiquidityCriterion(
                thresholds.min_liquidity,
            ),
            DailyRangeCriterion(
                thresholds.max_daily_volatility,
            ),
        ]

    def _buzz_should_pass(
        self,
        thresholds: StrategyThresholds,
    ) -> list[TechnicalCriterion]:
        # Momentum checks affect score/reporting without automatically
        # rejecting a socially trending stock.
        return [
            RsiRangeCriterion(
                max_rsi=thresholds.rsi_overbought,
            ),
            VolumeExpansionCriterion(
                thresholds.volume_above_avg_ratio,
            ),
            MacdBullishCriterion(
                require_above_signal=True,
            ),
            StochasticHealthCriterion(
                max_k=thresholds.stoch_overbought,
            ),
        ]

    def _nightly_must_pass(
        self,
        thresholds: StrategyThresholds,
        indicators: IndicatorParameters,
    ) -> list[TechnicalCriterion]:
        return [
            PriceAboveMaCriterion(
                indicators.ma_mid,
            ),
            MaAlignmentCriterion(
                indicators.ma_mid,
                indicators.ma_long,
            ),
            MacdBullishCriterion(
                require_above_signal=True,
            ),
            RsiRangeCriterion(
                min_rsi=thresholds.rsi_healthy_min,
            ),
            RsiRangeCriterion(
                max_rsi=thresholds.rsi_overbought,
            ),
            LiquidityCriterion(
                thresholds.min_liquidity,
            ),
            MinimumPriceCriterion(
                thresholds.min_price,
            ),
            VolumeExpansionCriterion(
                thresholds.volume_above_avg_ratio,
            ),
        ]

    def _nightly_should_pass(
        self,
        thresholds: StrategyThresholds,
        indicators: IndicatorParameters,
    ) -> list[TechnicalCriterion]:
        return [
            PriceAboveMaCriterion(
                indicators.ma_long,
            ),
            AdxTrendCriterion(
                thresholds.adx_min,
                thresholds.adx_max,
                require_direction=True,
            ),
            BollingerPositionCriterion(),
            VolumeExpansionCriterion(
                thresholds.volume_dry_ratio,
            ),
            MfiThresholdCriterion(
                thresholds.mfi_overbought,
            ),
            AtrRangeCriterion(
                thresholds.atr_min_pct,
                thresholds.atr_max_pct,
            ),
        ]


def create_strategy_from_config(
    config: AppConfig,
    strategy_name: StrategyName | None = None,
) -> TechnicalStrategy:
    selected_name = strategy_name or config.analysis.active_strategy
    thresholds = config.strategies.get(selected_name)

    if thresholds is None:
        raise ValueError(f"Strategy thresholds are not configured: {selected_name.value}")

    return TechnicalStrategyFactory().create(
        strategy_name=selected_name,
        thresholds=thresholds,
        scoring=config.scoring,
        indicators=config.indicators,
    )


def create_technical_strategies(
    config: AppConfig,
) -> TechnicalStrategies:
    return TechnicalStrategies(
        active_name=config.analysis.active_strategy,
        active=create_strategy_from_config(config),
        buzz=create_strategy_from_config(
            config,
            StrategyName.BUZZ,
        ),
    )
