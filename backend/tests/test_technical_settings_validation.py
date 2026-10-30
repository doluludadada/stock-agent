from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest
import yaml
from icontract.errors import ViolationError
from pydantic import ValidationError

from a_domain.model.analysis.technical_settings import TechnicalSettings
from a_domain.rules.technical.calculation.parameters import IndicatorParameters
from a_domain.rules.technical.criteria.volume import ObvTrendCriterion
from a_domain.rules.technical.strategy import TechnicalRule, TechnicalScoring, TechnicalStrategy
from a_domain.types.enums import RuleEffect
from b_application.pipeline import Pipeline
from c_infrastructure.technical.yaml_technical_settings_repository import YamlTechnicalSettingsRepository


def settings_document(*, defaults: dict[str, Any] | None = None, **strategy: Any) -> dict[str, Any]:
    main = {"rules": [{"type": "price_above_ma", "effect": "block_on_fail", "period": 20}], **strategy}
    return {"active_strategy_id": "main", "buzz_strategy_id": "main", "defaults": defaults or {}, "strategies": {"main": main}}


async def load(tmp_path: Path, document: dict[str, Any]) -> TechnicalSettings:
    template = tmp_path / "technical.yaml"
    template.write_text(yaml.safe_dump(document), encoding="utf-8")
    return await YamlTechnicalSettingsRepository(template).load()


async def rejected_locations(tmp_path: Path, document: dict[str, Any]) -> list[tuple[str | int, ...]]:
    with pytest.raises(ValidationError) as error:
        await load(tmp_path, document)

    return [tuple(detail["loc"]) for detail in error.value.errors()]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "criterion_type", ["rsi_rnage", "RsiRangeCriterion", "a_domain.rules.technical.criteria.momentum.RsiRangeCriterion"]
)
async def test_unknown_criterion_type_is_rejected_at_load(tmp_path: Path, criterion_type: str) -> None:
    document = settings_document(rules=[{"type": criterion_type, "effect": "block_on_fail"}])

    assert await rejected_locations(tmp_path, document) == [("strategies", "main", "rules", 0)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rule", "location"),
    [
        ({"type": "rsi_range", "effect": "block_on_fail", "max_rs": 70}, ("rsi_range", "max_rs")),
        ({"type": "rsi_range", "effect": "block_on_fail", "max_rsi": 120}, ("rsi_range", "max_rsi")),
        ({"type": "rsi_range", "effect": "must_pass", "max_rsi": 70}, ("rsi_range", "effect")),
        ({"type": "daily_range", "effect": "block_on_fail"}, ("daily_range", "max_daily_range_pct")),
        ({"type": "minimum_price", "effect": "block_on_fail", "min_price": float("inf")}, ("minimum_price", "min_price")),
        ({"type": "rsi_range", "effect": "block_on_fail", "min_rsi": 90, "max_rsi": 10}, ("rsi_range", "max_rsi")),
        ({"type": "adx_trend", "effect": "block_on_fail", "min_adx": 40, "max_adx": 30}, ("adx_trend", "max_adx")),
        ({"type": "golden_cross", "effect": "block_on_fail", "fast": 60, "slow": 20}, ("golden_cross", "slow")),
        ({"type": "ma_alignment", "effect": "block_on_fail", "fast": 60, "slow": 20}, ("ma_alignment", "slow")),
        ({"type": "atr_range", "effect": "block_on_fail"}, ("atr_range", "max_atr_pct")),
        ({"type": "atr_range", "effect": "block_on_fail", "min_atr_pct": 0.05, "max_atr_pct": 0.01}, ("atr_range", "max_atr_pct")),
    ],
)
async def test_invalid_criterion_parameter_is_rejected_at_its_field(
    tmp_path: Path, rule: dict[str, Any], location: tuple[str, ...]
) -> None:
    document = settings_document(rules=[rule])

    assert await rejected_locations(tmp_path, document) == [("strategies", "main", "rules", 0, *location)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("defaults", "location"),
    [
        ({"indicators": {"rsi_period": 0}}, ("indicators", "rsi_period")),
        ({"indicators": {"rsi_perod": 7}}, ("indicators", "rsi_perod")),
        ({"indicators": {"macd_fast": 30}}, ("indicators", "macd_slow")),
        ({"indicators": {"ma_short": 20}}, ("indicators", "ma_mid")),
        ({"indicators": {"bb_std": float("inf")}}, ("indicators", "bb_std")),
        ({"indicators": {"bb_std": 1e308}}, ("indicators", "bb_std")),
        ({"scoring": {"base_score": 120}}, ("scoring", "base_score")),
    ],
)
async def test_invalid_default_is_rejected_at_its_field(tmp_path: Path, defaults: dict[str, Any], location: tuple[str, ...]) -> None:
    locations = await rejected_locations(tmp_path, settings_document(defaults=defaults))

    assert ("defaults", *location) in locations
    assert ("strategies", "main", *location) in locations


@pytest.mark.asyncio
async def test_strategy_inherits_defaults_it_does_not_override(tmp_path: Path) -> None:
    document = settings_document(defaults={"indicators": {"rsi_period": 7, "macd_fast": 5}}, indicators={"macd_fast": 8})

    strategy = (await load(tmp_path, document)).active_strategy

    assert (strategy.indicators.rsi_period, strategy.indicators.macd_fast) == (7, 8)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("indicators", "rule", "location"),
    [
        ({"ma_mid": 10}, {"type": "price_above_ma", "effect": "block_on_fail", "period": 20}, ("price_above_ma", "period")),
        ({"ma_long": 120}, {"type": "ma_alignment", "effect": "block_on_fail", "fast": 20, "slow": 60}, ("ma_alignment", "slow")),
        ({"ma_mid": 10}, {"type": "golden_cross", "effect": "increase_score_on_pass"}, ("golden_cross", "fast")),
        ({"ma_short": 10}, {"type": "volume_expansion", "effect": "block_on_fail", "min_ratio": 0.5}, ("volume_expansion", "period")),
    ],
)
async def test_rule_on_a_moving_average_the_strategy_does_not_calculate_is_rejected(
    tmp_path: Path, indicators: dict[str, int], rule: dict[str, Any], location: tuple[str, ...]
) -> None:
    document = settings_document(defaults={"indicators": indicators}, rules=[rule])

    assert await rejected_locations(tmp_path, document) == [("strategies", "main", "rules", 0, *location)]


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["active_strategy_id", "buzz_strategy_id"])
async def test_selected_strategy_must_exist(tmp_path: Path, field: str) -> None:
    document = {**settings_document(), field: "missing"}

    assert await rejected_locations(tmp_path, document) == [(field,)]


class Unreachable:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"The workflow used {name} before its technical settings were validated")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("workflow", "arguments"),
    [("run_full_cycle", ()), ("run_buzz_scan", ()), ("run_intraday", ()), ("analyse_specific_stocks", (["2330"],))],
)
async def test_invalid_settings_stop_every_workflow_before_it_starts(
    tmp_path: Path, workflow: str, arguments: tuple[Any, ...]
) -> None:
    template = tmp_path / "technical.yaml"
    template.write_text(yaml.safe_dump(settings_document(rules=[{"type": "rsi_rnage", "effect": "block_on_fail"}])), encoding="utf-8")
    dependencies: dict[str, Any] = {field.name: Unreachable() for field in fields(Pipeline)}
    dependencies["technical_settings_repository"] = YamlTechnicalSettingsRepository(template)

    with pytest.raises(ValidationError):
        await getattr(Pipeline(**dependencies), workflow)(*arguments)


MAIN_STRATEGY = TechnicalStrategy(
    strategy_id="main",
    indicators=IndicatorParameters(),
    scoring=TechnicalScoring(),
    rules=(TechnicalRule(criterion=ObvTrendCriterion(), effect=RuleEffect.INCREASE_SCORE_ON_PASS),),
)


@pytest.mark.parametrize(
    ("active_strategy_id", "buzz_strategy_id", "strategies"),
    [("missing", "main", (MAIN_STRATEGY,)), ("main", "missing", (MAIN_STRATEGY,)), ("main", "main", (MAIN_STRATEGY, MAIN_STRATEGY))],
)
def test_technical_settings_require_unique_strategies_and_existing_selections(
    active_strategy_id: str, buzz_strategy_id: str, strategies: tuple[TechnicalStrategy, ...]
) -> None:
    with pytest.raises(ViolationError):
        TechnicalSettings(active_strategy_id=active_strategy_id, buzz_strategy_id=buzz_strategy_id, strategies=strategies)
