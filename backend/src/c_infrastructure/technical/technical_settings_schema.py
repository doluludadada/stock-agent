# backend/src/c_infrastructure/technical/technical_settings_schema.py
# Source: :contentReference[oaicite:0]{index=0}

from dataclasses import replace
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from a_domain.model.analysis.technical_settings import TechnicalSettings
from a_domain.rules.technical.calculation.parameters import IndicatorParameters
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
from a_domain.rules.technical.strategy import TechnicalRule, TechnicalScoring, TechnicalStrategy
from a_domain.types.enums import RuleEffect, TechnicalCriterionType


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BaseTechnicalRuleSchema(StrictSchema):
    effect: RuleEffect


# ---------------------------------------------------------------------------- #
#                                  Momentum                                    #
# ---------------------------------------------------------------------------- #


class RsiRangeRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.RSI_RANGE] = TechnicalCriterionType.RSI_RANGE
    min_rsi: float = Field(default=0, ge=0, le=100)
    max_rsi: float = Field(default=100, ge=0, le=100)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.min_rsi > self.max_rsi:
            raise ValueError("min_rsi must be <= max_rsi")

        return self

    def to_domain(self) -> TechnicalRule:
        criterion = RsiRangeCriterion(min_rsi=self.min_rsi, max_rsi=self.max_rsi)
        return TechnicalRule(criterion=criterion, effect=self.effect)


class MfiThresholdRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.MFI_THRESHOLD] = TechnicalCriterionType.MFI_THRESHOLD
    max_mfi: float = Field(default=80, ge=0, le=100)

    def to_domain(self) -> TechnicalRule:
        criterion = MfiThresholdCriterion(max_mfi=self.max_mfi)
        return TechnicalRule(criterion=criterion, effect=self.effect)


class MacdBullishRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.MACD_BULLISH] = TechnicalCriterionType.MACD_BULLISH
    require_above_signal: bool = True
    require_positive: bool = False
    require_histogram_positive: bool = False

    def to_domain(self) -> TechnicalRule:
        criterion = MacdBullishCriterion(
            require_above_signal=self.require_above_signal,
            require_positive=self.require_positive,
            require_histogram_positive=self.require_histogram_positive,
        )
        return TechnicalRule(criterion=criterion, effect=self.effect)


class StochasticHealthRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.STOCHASTIC_HEALTH] = TechnicalCriterionType.STOCHASTIC_HEALTH
    max_k: float | None = Field(default=80, ge=0, le=100)
    require_k_above_d: bool = False

    def to_domain(self) -> TechnicalRule:
        criterion = StochasticHealthCriterion(max_k=self.max_k, require_k_above_d=self.require_k_above_d)
        return TechnicalRule(criterion=criterion, effect=self.effect)


# ---------------------------------------------------------------------------- #
#                                    Trend                                     #
# ---------------------------------------------------------------------------- #


class AdxTrendRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.ADX_TREND] = TechnicalCriterionType.ADX_TREND
    min_adx: float = Field(default=20, ge=0, le=100)
    max_adx: float = Field(default=50, ge=0, le=100)
    require_direction: bool = True

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.min_adx > self.max_adx:
            raise ValueError("min_adx must be <= max_adx")

        return self

    def to_domain(self) -> TechnicalRule:
        criterion = AdxTrendCriterion(min_adx=self.min_adx, max_adx=self.max_adx, require_direction=self.require_direction)
        return TechnicalRule(criterion=criterion, effect=self.effect)


class GoldenCrossRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.GOLDEN_CROSS] = TechnicalCriterionType.GOLDEN_CROSS
    fast: int = Field(default=20, gt=0)
    slow: int = Field(default=60, gt=0)
    max_cross_margin: float = Field(default=0.03, gt=0)

    @model_validator(mode="after")
    def validate_periods(self) -> Self:
        if self.fast >= self.slow:
            raise ValueError("fast must be smaller than slow")

        return self

    def to_domain(self) -> TechnicalRule:
        criterion = GoldenCrossCriterion(fast=self.fast, slow=self.slow, max_cross_margin=self.max_cross_margin)
        return TechnicalRule(criterion=criterion, effect=self.effect)


class MaAlignmentRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.MA_ALIGNMENT] = TechnicalCriterionType.MA_ALIGNMENT
    fast: int = Field(default=20, gt=0)
    slow: int = Field(default=60, gt=0)

    @model_validator(mode="after")
    def validate_periods(self) -> Self:
        if self.fast >= self.slow:
            raise ValueError("fast must be smaller than slow")

        return self

    def to_domain(self) -> TechnicalRule:
        criterion = MaAlignmentCriterion(fast=self.fast, slow=self.slow)
        return TechnicalRule(criterion=criterion, effect=self.effect)


class PriceAboveMaRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.PRICE_ABOVE_MA] = TechnicalCriterionType.PRICE_ABOVE_MA
    period: int = Field(gt=0)

    def to_domain(self) -> TechnicalRule:
        criterion = PriceAboveMaCriterion(period=self.period)
        return TechnicalRule(criterion=criterion, effect=self.effect)


# ---------------------------------------------------------------------------- #
#                                  Volatility                                  #
# ---------------------------------------------------------------------------- #


class AtrRangeRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.ATR_RANGE] = TechnicalCriterionType.ATR_RANGE
    min_atr_pct: float | None = Field(default=None, ge=0)
    max_atr_pct: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.min_atr_pct is None and self.max_atr_pct is None:
            raise ValueError("ATR range requires at least one boundary")

        if self.min_atr_pct is not None and self.max_atr_pct is not None and self.min_atr_pct > self.max_atr_pct:
            raise ValueError("min_atr_pct must be <= max_atr_pct")

        return self

    def to_domain(self) -> TechnicalRule:
        criterion = AtrRangeCriterion(min_atr_pct=self.min_atr_pct, max_atr_pct=self.max_atr_pct)
        return TechnicalRule(criterion=criterion, effect=self.effect)


class BollingerPositionRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.BOLLINGER_POSITION] = TechnicalCriterionType.BOLLINGER_POSITION

    def to_domain(self) -> TechnicalRule:
        criterion = BollingerPositionCriterion()
        return TechnicalRule(criterion=criterion, effect=self.effect)


class BollingerSqueezeRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.BOLLINGER_SQUEEZE] = TechnicalCriterionType.BOLLINGER_SQUEEZE
    max_bandwidth: float = Field(default=0.1, gt=0)

    def to_domain(self) -> TechnicalRule:
        criterion = BollingerSqueezeCriterion(max_bandwidth=self.max_bandwidth)
        return TechnicalRule(criterion=criterion, effect=self.effect)


class BollingerThresholdRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.BOLLINGER_THRESHOLD] = TechnicalCriterionType.BOLLINGER_THRESHOLD
    max_percent_b: float = Field(default=0.9, gt=0)

    def to_domain(self) -> TechnicalRule:
        criterion = BollingerThresholdCriterion(max_percent_b=self.max_percent_b)
        return TechnicalRule(criterion=criterion, effect=self.effect)


class DailyRangeRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.DAILY_RANGE] = TechnicalCriterionType.DAILY_RANGE
    max_daily_range_pct: float = Field(gt=0)

    def to_domain(self) -> TechnicalRule:
        criterion = DailyRangeCriterion(max_daily_range_pct=self.max_daily_range_pct)
        return TechnicalRule(criterion=criterion, effect=self.effect)


# ---------------------------------------------------------------------------- #
#                                    Volume                                    #
# ---------------------------------------------------------------------------- #


class LiquidityRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.LIQUIDITY] = TechnicalCriterionType.LIQUIDITY
    min_daily_volume: int = Field(default=500, ge=0)

    def to_domain(self) -> TechnicalRule:
        criterion = LiquidityCriterion(min_daily_volume=self.min_daily_volume)
        return TechnicalRule(criterion=criterion, effect=self.effect)


class MinimumPriceRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.MINIMUM_PRICE] = TechnicalCriterionType.MINIMUM_PRICE
    min_price: float = Field(default=15, gt=0)

    def to_domain(self) -> TechnicalRule:
        criterion = MinimumPriceCriterion(min_price=self.min_price)
        return TechnicalRule(criterion=criterion, effect=self.effect)


class ObvTrendRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.OBV_TREND] = TechnicalCriterionType.OBV_TREND

    def to_domain(self) -> TechnicalRule:
        criterion = ObvTrendCriterion()
        return TechnicalRule(criterion=criterion, effect=self.effect)


class VolumeExpansionRuleSchema(BaseTechnicalRuleSchema):
    type: Literal[TechnicalCriterionType.VOLUME_EXPANSION] = TechnicalCriterionType.VOLUME_EXPANSION
    min_ratio: float = Field(default=1, gt=0)
    period: int = Field(default=5, gt=0)

    def to_domain(self) -> TechnicalRule:
        criterion = VolumeExpansionCriterion(min_ratio=self.min_ratio, period=self.period)
        return TechnicalRule(criterion=criterion, effect=self.effect)


TechnicalRuleSchema = Annotated[
    RsiRangeRuleSchema
    | MfiThresholdRuleSchema
    | MacdBullishRuleSchema
    | StochasticHealthRuleSchema
    | AdxTrendRuleSchema
    | GoldenCrossRuleSchema
    | MaAlignmentRuleSchema
    | PriceAboveMaRuleSchema
    | AtrRangeRuleSchema
    | BollingerPositionRuleSchema
    | BollingerSqueezeRuleSchema
    | BollingerThresholdRuleSchema
    | DailyRangeRuleSchema
    | LiquidityRuleSchema
    | MinimumPriceRuleSchema
    | ObvTrendRuleSchema
    | VolumeExpansionRuleSchema,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------- #
#                              Strategy Settings                               #
# ---------------------------------------------------------------------------- #


class IndicatorOverridesSchema(StrictSchema):
    rsi_period: int | None = Field(default=None, gt=0)

    macd_fast: int | None = Field(default=None, gt=0)
    macd_slow: int | None = Field(default=None, gt=0)
    macd_signal: int | None = Field(default=None, gt=0)

    ma_short: int | None = Field(default=None, gt=0)
    ma_mid: int | None = Field(default=None, gt=0)
    ma_long: int | None = Field(default=None, gt=0)

    bb_period: int | None = Field(default=None, gt=0)
    bb_std: float | None = Field(default=None, gt=0)

    stoch_k: int | None = Field(default=None, gt=0)
    stoch_d: int | None = Field(default=None, gt=0)

    adx_period: int | None = Field(default=None, gt=0)
    atr_period: int | None = Field(default=None, gt=0)
    mfi_period: int | None = Field(default=None, gt=0)

    def apply(self, defaults: IndicatorParameters) -> IndicatorParameters:
        overrides = self.model_dump(exclude_none=True)
        return replace(defaults, **overrides)


class ScoringOverridesSchema(StrictSchema):
    base_score: int | None = Field(default=None, ge=0, le=100)
    block_failure_penalty: int | None = Field(default=None, ge=0)
    failure_score_reduction: int | None = Field(default=None, ge=0)
    pass_score_increase: int | None = Field(default=None, ge=0)

    def apply(self, defaults: TechnicalScoring) -> TechnicalScoring:
        overrides = self.model_dump(exclude_none=True)
        return replace(defaults, **overrides)


class TechnicalDefaultsSchema(StrictSchema):
    indicators: IndicatorParameters = Field(default_factory=IndicatorParameters)
    scoring: TechnicalScoring = Field(default_factory=TechnicalScoring)


class TechnicalStrategySchema(StrictSchema):
    indicators: IndicatorOverridesSchema = Field(default_factory=IndicatorOverridesSchema)
    scoring: ScoringOverridesSchema = Field(default_factory=ScoringOverridesSchema)
    rules: list[TechnicalRuleSchema] = Field(min_length=1)

    def to_domain(self, strategy_id: str, defaults: TechnicalDefaultsSchema) -> TechnicalStrategy:
        return TechnicalStrategy(
            strategy_id=strategy_id,
            indicators=self.indicators.apply(defaults.indicators),
            scoring=self.scoring.apply(defaults.scoring),
            rules=tuple(rule.to_domain() for rule in self.rules),
        )


class TechnicalSettingsSchema(StrictSchema):
    active_strategy_id: str = Field(min_length=1)
    buzz_strategy_id: str = Field(min_length=1)
    defaults: TechnicalDefaultsSchema = Field(default_factory=TechnicalDefaultsSchema)
    strategies: dict[str, TechnicalStrategySchema] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_strategy_ids(self) -> Self:
        if any(not strategy_id.strip() for strategy_id in self.strategies):
            raise ValueError("Technical strategy ID must not be empty")

        if self.active_strategy_id not in self.strategies:
            raise ValueError(f"Active technical strategy not found: {self.active_strategy_id}")

        if self.buzz_strategy_id not in self.strategies:
            raise ValueError(f"Buzz technical strategy not found: {self.buzz_strategy_id}")

        return self

    def to_domain(self) -> TechnicalSettings:
        strategies = tuple(strategy.to_domain(strategy_id, self.defaults) for strategy_id, strategy in self.strategies.items())

        return TechnicalSettings(
            active_strategy_id=self.active_strategy_id, buzz_strategy_id=self.buzz_strategy_id, strategies=strategies
        )
