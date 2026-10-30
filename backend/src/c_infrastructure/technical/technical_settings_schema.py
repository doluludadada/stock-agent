# backend/src/c_infrastructure/technical/technical_settings_schema.py

from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Any, ClassVar, Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_core import InitErrorDetails, PydanticCustomError

from a_domain.model.analysis.technical_settings import TechnicalSettings
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
from a_domain.rules.technical.strategy import TechnicalRule, TechnicalScoring, TechnicalStrategy
from a_domain.types.enums import RuleEffect


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def raise_field_errors(model: BaseModel, errors: list[InitErrorDetails]) -> None:
    if errors:
        raise ValidationError.from_exception_data(type(model).__name__, errors)


def field_error(loc: tuple[str | int, ...], message: str, value: Any) -> InitErrorDetails:
    return InitErrorDetails(type=PydanticCustomError("technical_settings", message), loc=loc, input=value)


class BaseTechnicalRuleSchema(StrictSchema):
    """
    One rule of a strategy.

    `type` selects the domain criterion. Every other field except `effect` is a
    constructor argument of that criterion, under the same name.
    """

    criterion: ClassVar[Callable[..., TechnicalCriterion]]
    price_ma_fields: ClassVar[tuple[str, ...]] = ()
    volume_ma_fields: ClassVar[tuple[str, ...]] = ()

    type: str
    effect: RuleEffect

    def to_domain(self) -> TechnicalRule:
        parameters = self.model_dump(exclude={"type", "effect"})
        return TechnicalRule(criterion=self.criterion(**parameters), effect=self.effect)


# ---------------------------------------------------------------------------- #
#                                  Momentum                                    #
# ---------------------------------------------------------------------------- #


class RsiRangeRuleSchema(BaseTechnicalRuleSchema):
    criterion = RsiRangeCriterion
    type: Literal["rsi_range"] = "rsi_range"
    min_rsi: float = Field(default=RsiRangeCriterion.min_rsi, ge=0, le=100)
    max_rsi: float = Field(default=RsiRangeCriterion.max_rsi, ge=0, le=100)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.min_rsi > self.max_rsi:
            raise_field_errors(self, [field_error(("max_rsi",), "max_rsi must be >= min_rsi", self.max_rsi)])

        return self


class MfiThresholdRuleSchema(BaseTechnicalRuleSchema):
    criterion = MfiThresholdCriterion
    type: Literal["mfi_threshold"] = "mfi_threshold"
    max_mfi: float = Field(default=MfiThresholdCriterion.max_mfi, ge=0, le=100)


class MacdBullishRuleSchema(BaseTechnicalRuleSchema):
    criterion = MacdBullishCriterion
    type: Literal["macd_bullish"] = "macd_bullish"
    require_above_signal: bool = MacdBullishCriterion.require_above_signal
    require_positive: bool = MacdBullishCriterion.require_positive
    require_histogram_positive: bool = MacdBullishCriterion.require_histogram_positive


class StochasticHealthRuleSchema(BaseTechnicalRuleSchema):
    criterion = StochasticHealthCriterion
    type: Literal["stochastic_health"] = "stochastic_health"
    max_k: float | None = Field(default=StochasticHealthCriterion.max_k, ge=0, le=100)
    require_k_above_d: bool = StochasticHealthCriterion.require_k_above_d


# ---------------------------------------------------------------------------- #
#                                    Trend                                     #
# ---------------------------------------------------------------------------- #


class AdxTrendRuleSchema(BaseTechnicalRuleSchema):
    criterion = AdxTrendCriterion
    type: Literal["adx_trend"] = "adx_trend"
    min_adx: float = Field(default=AdxTrendCriterion.min_adx, ge=0, le=100)
    max_adx: float = Field(default=AdxTrendCriterion.max_adx, ge=0, le=100)
    require_direction: bool = AdxTrendCriterion.require_direction

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.min_adx > self.max_adx:
            raise_field_errors(self, [field_error(("max_adx",), "max_adx must be >= min_adx", self.max_adx)])

        return self


class GoldenCrossRuleSchema(BaseTechnicalRuleSchema):
    criterion = GoldenCrossCriterion
    price_ma_fields = ("fast", "slow")
    type: Literal["golden_cross"] = "golden_cross"
    fast: int = Field(default=GoldenCrossCriterion.fast, gt=0)
    slow: int = Field(default=GoldenCrossCriterion.slow, gt=0)
    max_cross_margin: float = Field(default=GoldenCrossCriterion.max_cross_margin, gt=0)

    @model_validator(mode="after")
    def validate_periods(self) -> Self:
        if self.fast >= self.slow:
            raise_field_errors(self, [field_error(("slow",), "slow must be greater than fast", self.slow)])

        return self


class MaAlignmentRuleSchema(BaseTechnicalRuleSchema):
    criterion = MaAlignmentCriterion
    price_ma_fields = ("fast", "slow")
    type: Literal["ma_alignment"] = "ma_alignment"
    fast: int = Field(default=MaAlignmentCriterion.fast, gt=0)
    slow: int = Field(default=MaAlignmentCriterion.slow, gt=0)

    @model_validator(mode="after")
    def validate_periods(self) -> Self:
        if self.fast >= self.slow:
            raise_field_errors(self, [field_error(("slow",), "slow must be greater than fast", self.slow)])

        return self


class PriceAboveMaRuleSchema(BaseTechnicalRuleSchema):
    criterion = PriceAboveMaCriterion
    price_ma_fields = ("period",)
    type: Literal["price_above_ma"] = "price_above_ma"
    period: int = Field(gt=0)


# ---------------------------------------------------------------------------- #
#                                  Volatility                                  #
# ---------------------------------------------------------------------------- #


class AtrRangeRuleSchema(BaseTechnicalRuleSchema):
    criterion = AtrRangeCriterion
    type: Literal["atr_range"] = "atr_range"
    min_atr_pct: float | None = Field(default=AtrRangeCriterion.min_atr_pct, ge=0)
    max_atr_pct: float | None = Field(default=AtrRangeCriterion.max_atr_pct, gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.min_atr_pct is None and self.max_atr_pct is None:
            raise_field_errors(self, [field_error(("max_atr_pct",), "Set min_atr_pct, max_atr_pct, or both", None)])

        if self.min_atr_pct is not None and self.max_atr_pct is not None and self.min_atr_pct > self.max_atr_pct:
            raise_field_errors(self, [field_error(("max_atr_pct",), "max_atr_pct must be >= min_atr_pct", self.max_atr_pct)])

        return self


class BollingerPositionRuleSchema(BaseTechnicalRuleSchema):
    criterion = BollingerPositionCriterion
    type: Literal["bollinger_position"] = "bollinger_position"


class BollingerSqueezeRuleSchema(BaseTechnicalRuleSchema):
    criterion = BollingerSqueezeCriterion
    type: Literal["bollinger_squeeze"] = "bollinger_squeeze"
    max_bandwidth: float = Field(default=BollingerSqueezeCriterion.max_bandwidth, gt=0)


class BollingerThresholdRuleSchema(BaseTechnicalRuleSchema):
    criterion = BollingerThresholdCriterion
    type: Literal["bollinger_threshold"] = "bollinger_threshold"
    max_percent_b: float = Field(default=BollingerThresholdCriterion.max_percent_b, gt=0)


class DailyRangeRuleSchema(BaseTechnicalRuleSchema):
    criterion = DailyRangeCriterion
    type: Literal["daily_range"] = "daily_range"
    max_daily_range_pct: float = Field(gt=0)


# ---------------------------------------------------------------------------- #
#                                    Volume                                    #
# ---------------------------------------------------------------------------- #


class LiquidityRuleSchema(BaseTechnicalRuleSchema):
    criterion = LiquidityCriterion
    type: Literal["liquidity"] = "liquidity"
    min_daily_volume: int = Field(default=LiquidityCriterion.min_daily_volume, ge=0)


class MinimumPriceRuleSchema(BaseTechnicalRuleSchema):
    criterion = MinimumPriceCriterion
    type: Literal["minimum_price"] = "minimum_price"
    min_price: float = Field(default=MinimumPriceCriterion.min_price, gt=0)


class ObvTrendRuleSchema(BaseTechnicalRuleSchema):
    criterion = ObvTrendCriterion
    type: Literal["obv_trend"] = "obv_trend"


class VolumeExpansionRuleSchema(BaseTechnicalRuleSchema):
    criterion = VolumeExpansionCriterion
    volume_ma_fields = ("period",)
    type: Literal["volume_expansion"] = "volume_expansion"
    min_ratio: float = Field(default=VolumeExpansionCriterion.min_ratio, gt=0)
    period: int = Field(default=VolumeExpansionCriterion.period, gt=0)


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

RULE_SCHEMA_BY_CRITERION: dict[Callable[..., TechnicalCriterion], type[BaseTechnicalRuleSchema]] = {
    schema.criterion: schema for schema in get_args(get_args(TechnicalRuleSchema)[0])
}


def rule_document(rule: TechnicalRule) -> dict[str, Any]:
    schema = RULE_SCHEMA_BY_CRITERION[type(rule.criterion)]
    return {"type": schema.model_fields["type"].default, "effect": rule.effect, **vars(rule.criterion)}


# ---------------------------------------------------------------------------- #
#                              Strategy Settings                               #
# ---------------------------------------------------------------------------- #

DEFAULT_INDICATORS = IndicatorParameters()
DEFAULT_SCORING = TechnicalScoring()


class IndicatorParametersSchema(StrictSchema):
    rsi_period: int = Field(default=DEFAULT_INDICATORS.rsi_period, gt=0)

    macd_fast: int = Field(default=DEFAULT_INDICATORS.macd_fast, gt=0)
    macd_slow: int = Field(default=DEFAULT_INDICATORS.macd_slow, gt=0)
    macd_signal: int = Field(default=DEFAULT_INDICATORS.macd_signal, gt=0)

    ma_short: int = Field(default=DEFAULT_INDICATORS.ma_short, gt=0)
    ma_mid: int = Field(default=DEFAULT_INDICATORS.ma_mid, gt=0)
    ma_long: int = Field(default=DEFAULT_INDICATORS.ma_long, gt=0)

    bb_period: int = Field(default=DEFAULT_INDICATORS.bb_period, gt=0)
    bb_std: float = Field(default=DEFAULT_INDICATORS.bb_std, gt=0, le=10)

    stoch_k: int = Field(default=DEFAULT_INDICATORS.stoch_k, gt=0)
    stoch_d: int = Field(default=DEFAULT_INDICATORS.stoch_d, gt=0)

    adx_period: int = Field(default=DEFAULT_INDICATORS.adx_period, gt=0)
    atr_period: int = Field(default=DEFAULT_INDICATORS.atr_period, gt=0)
    mfi_period: int = Field(default=DEFAULT_INDICATORS.mfi_period, gt=0)

    @model_validator(mode="after")
    def validate_period_order(self) -> Self:
        errors: list[InitErrorDetails] = []

        if self.macd_slow <= self.macd_fast:
            errors.append(field_error(("macd_slow",), "macd_slow must be greater than macd_fast", self.macd_slow))

        if self.ma_mid <= self.ma_short:
            errors.append(field_error(("ma_mid",), "ma_mid must be greater than ma_short", self.ma_mid))

        if self.ma_long <= self.ma_mid:
            errors.append(field_error(("ma_long",), "ma_long must be greater than ma_mid", self.ma_long))

        raise_field_errors(self, errors)
        return self

    def to_domain(self) -> IndicatorParameters:
        return IndicatorParameters(**self.model_dump())


class TechnicalScoringSchema(StrictSchema):
    base_score: int = Field(default=DEFAULT_SCORING.base_score, ge=0, le=100)
    block_failure_penalty: int = Field(default=DEFAULT_SCORING.block_failure_penalty, ge=0)
    failure_score_reduction: int = Field(default=DEFAULT_SCORING.failure_score_reduction, ge=0)
    pass_score_increase: int = Field(default=DEFAULT_SCORING.pass_score_increase, ge=0)

    def to_domain(self) -> TechnicalScoring:
        return TechnicalScoring(**self.model_dump())


class TechnicalDefaultsSchema(StrictSchema):
    indicators: IndicatorParametersSchema = Field(default_factory=IndicatorParametersSchema)
    scoring: TechnicalScoringSchema = Field(default_factory=TechnicalScoringSchema)


class TechnicalStrategySchema(StrictSchema):
    indicators: IndicatorParametersSchema = Field(default_factory=IndicatorParametersSchema)
    scoring: TechnicalScoringSchema = Field(default_factory=TechnicalScoringSchema)
    rules: list[TechnicalRuleSchema] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_moving_average_periods(self) -> Self:
        indicators = self.indicators.to_domain()
        errors: list[InitErrorDetails] = []

        for index, rule in enumerate(self.rules):
            for kind, fields, calculated_periods in (
                ("MA", rule.price_ma_fields, indicators.price_ma_periods),
                ("Volume MA", rule.volume_ma_fields, indicators.volume_ma_periods),
            ):
                for field in fields:
                    period = getattr(rule, field)

                    if period not in calculated_periods:
                        calculated = ", ".join(map(str, sorted(calculated_periods)))
                        message = (
                            f"{kind}_{period} is not calculated by this strategy's indicators. Calculated {kind} periods: {calculated}"
                        )
                        errors.append(field_error(("rules", index, rule.type, field), message, period))

        raise_field_errors(self, errors)
        return self

    def to_domain(self, strategy_id: str) -> TechnicalStrategy:
        return TechnicalStrategy(
            strategy_id=strategy_id,
            indicators=self.indicators.to_domain(),
            scoring=self.scoring.to_domain(),
            rules=tuple(rule.to_domain() for rule in self.rules),
        )


def inherit_defaults(defaults: Any, strategy: Any) -> Any:
    if not isinstance(defaults, dict) or not isinstance(strategy, dict):
        return strategy

    inherited = dict(strategy)
    for section in ("indicators", "scoring"):
        default_values = defaults.get(section) or {}
        values = strategy.get(section) or {}

        if isinstance(default_values, dict) and isinstance(values, dict):
            inherited[section] = {**default_values, **values}

    return inherited


class TechnicalSettingsSchema(StrictSchema):
    """
    The technical settings document: technical.yaml, technical.local.yaml and the UI payload.

    Each strategy inherits every `defaults.indicators` and `defaults.scoring` value it does
    not set itself, so validation always sees the values a workflow will use.
    """

    active_strategy_id: str = Field(min_length=1)
    buzz_strategy_id: str = Field(min_length=1)
    defaults: TechnicalDefaultsSchema = Field(default_factory=TechnicalDefaultsSchema)
    strategies: dict[str, TechnicalStrategySchema] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def apply_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict) or not isinstance(data.get("strategies"), dict):
            return data

        defaults = data.get("defaults") or {}
        strategies = {strategy_id: inherit_defaults(defaults, strategy) for strategy_id, strategy in data["strategies"].items()}
        return {**data, "strategies": strategies}

    @model_validator(mode="after")
    def validate_strategy_ids(self) -> Self:
        errors: list[InitErrorDetails] = [
            field_error(("strategies", strategy_id), "Technical strategy ID must not be blank", strategy_id)
            for strategy_id in self.strategies
            if not strategy_id.strip()
        ]

        for field, strategy_id in (("active_strategy_id", self.active_strategy_id), ("buzz_strategy_id", self.buzz_strategy_id)):
            if strategy_id not in self.strategies:
                errors.append(field_error((field,), f"Technical strategy not found: {strategy_id}", strategy_id))

        raise_field_errors(self, errors)
        return self

    def to_domain(self) -> TechnicalSettings:
        return TechnicalSettings(
            active_strategy_id=self.active_strategy_id,
            buzz_strategy_id=self.buzz_strategy_id,
            strategies=tuple(strategy.to_domain(strategy_id) for strategy_id, strategy in self.strategies.items()),
        )

    @classmethod
    def from_domain(cls, settings: TechnicalSettings) -> Self:
        return cls.model_validate(
            {
                "active_strategy_id": settings.active_strategy_id,
                "buzz_strategy_id": settings.buzz_strategy_id,
                "strategies": {
                    strategy.strategy_id: {
                        "indicators": asdict(strategy.indicators),
                        "scoring": asdict(strategy.scoring),
                        "rules": [rule_document(rule) for rule in strategy.rules],
                    }
                    for strategy in settings.strategies
                },
            }
        )

    def to_document(self) -> dict[str, Any]:
        """JSON-compatible settings. Every strategy carries its full indicator and scoring values, so `defaults` is left out."""
        return self.model_dump(mode="json", exclude={"defaults"})
