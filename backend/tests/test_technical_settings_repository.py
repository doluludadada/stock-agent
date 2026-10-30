import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from a_domain.model.analysis.technical_settings import TechnicalSettings
from c_infrastructure.technical.technical_settings_schema import TechnicalSettingsSchema
from c_infrastructure.technical.yaml_technical_settings_repository import YamlTechnicalSettingsRepository

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "config" / "technical.yaml"


@pytest.fixture
def template(tmp_path: Path) -> Path:
    path = tmp_path / "technical.yaml"
    shutil.copyfile(TEMPLATE_PATH, path)
    return path


def with_strategy(settings: TechnicalSettings, strategy_id: str, **changes: object) -> TechnicalSettings:
    strategies = tuple(
        replace(strategy, **changes) if strategy.strategy_id == strategy_id else strategy for strategy in settings.strategies
    )
    return replace(settings, strategies=strategies)


def leftover_temporary_files(template: Path) -> list[Path]:
    return sorted(template.parent.glob(".technical.local.yaml.*"))


@pytest.mark.asyncio
async def test_next_load_uses_saved_settings_and_template_stays_untouched(template: Path) -> None:
    template_text = template.read_text(encoding="utf-8")
    repository = YamlTechnicalSettingsRepository(template)
    settings = await repository.load()
    aggressive = settings.get_strategy("aggressive")
    edited = replace(
        with_strategy(settings, "aggressive", indicators=replace(aggressive.indicators, rsi_period=7, macd_fast=8)),
        active_strategy_id="aggressive",
        buzz_strategy_id="buzz_strict_confirmation",
    )

    await repository.save(edited)
    reloaded = await repository.load()

    assert reloaded == edited
    assert reloaded.active_strategy.indicators.rsi_period == 7
    assert reloaded.buzz_strategy.strategy_id == "buzz_strict_confirmation"
    assert template.read_text(encoding="utf-8") == template_text
    assert leftover_temporary_files(template) == []


@pytest.mark.asyncio
async def test_reset_deletes_the_saved_file_and_the_next_load_uses_the_template(template: Path) -> None:
    template_text = template.read_text(encoding="utf-8")
    repository = YamlTechnicalSettingsRepository(template)
    template_settings = await repository.load()
    await repository.save(replace(template_settings, active_strategy_id="conservative"))

    await repository.reset()
    await repository.reset()

    assert await repository.load() == template_settings
    assert not (template.parent / "technical.local.yaml").exists()
    assert template.read_text(encoding="utf-8") == template_text


@pytest.mark.asyncio
async def test_invalid_settings_are_rejected_at_their_field_and_nothing_is_written(template: Path) -> None:
    repository = YamlTechnicalSettingsRepository(template)
    settings = await repository.load()
    await repository.save(settings)
    saved_text = (template.parent / "technical.local.yaml").read_text(encoding="utf-8")
    aggressive = settings.get_strategy("aggressive")
    price_above_ma_20_with_ma_mid_10 = with_strategy(settings, "aggressive", indicators=replace(aggressive.indicators, ma_mid=10))

    with pytest.raises(ValidationError) as error:
        await repository.save(price_above_ma_20_with_ma_mid_10)

    assert ("strategies", "aggressive", "rules", 0, "price_above_ma", "period") in [detail["loc"] for detail in error.value.errors()]
    assert (template.parent / "technical.local.yaml").read_text(encoding="utf-8") == saved_text
    assert leftover_temporary_files(template) == []


@pytest.mark.asyncio
async def test_interrupted_save_keeps_the_previous_saved_file(template: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = YamlTechnicalSettingsRepository(template)
    settings = await repository.load()
    await repository.save(settings)
    saved_text = (template.parent / "technical.local.yaml").read_text(encoding="utf-8")

    def fail_before_the_file_is_durable(descriptor: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("os.fsync", fail_before_the_file_is_durable)

    with pytest.raises(OSError, match="disk full"):
        await repository.save(replace(settings, active_strategy_id="conservative"))

    assert (template.parent / "technical.local.yaml").read_text(encoding="utf-8") == saved_text
    assert (await repository.load()).active_strategy_id == "moderate"
    assert leftover_temporary_files(template) == []


@pytest.mark.asyncio
async def test_ui_document_shows_current_values_and_saves_edits(template: Path) -> None:
    repository = YamlTechnicalSettingsRepository(template)
    document = TechnicalSettingsSchema.from_domain(await repository.load()).to_document()
    moderate = document["strategies"]["moderate"]

    assert json.loads(json.dumps(document)) == document
    assert (document["active_strategy_id"], document["buzz_strategy_id"]) == ("moderate", "buzz_safety_only")
    assert moderate["indicators"]["rsi_period"] == 14
    assert moderate["scoring"]["base_score"] == 50
    assert moderate["rules"][0] == {"type": "price_above_ma", "effect": "block_on_fail", "period": 20}

    moderate["indicators"]["rsi_period"] = 9
    await repository.save(TechnicalSettingsSchema.model_validate(document).to_domain())

    assert (await repository.load()).active_strategy.indicators.rsi_period == 9


@pytest.mark.asyncio
async def test_invalid_ui_document_is_rejected_at_its_field(template: Path) -> None:
    document = TechnicalSettingsSchema.from_domain(await YamlTechnicalSettingsRepository(template).load()).to_document()
    document["strategies"]["moderate"]["indicators"]["macd_fast"] = 30
    document["strategies"]["moderate"]["rules"][3]["min_rsi"] = 120

    with pytest.raises(ValidationError) as error:
        TechnicalSettingsSchema.model_validate(document)

    assert [detail["loc"] for detail in error.value.errors()] == [
        ("strategies", "moderate", "indicators", "macd_slow"),
        ("strategies", "moderate", "rules", 3, "rsi_range", "min_rsi"),
    ]


DUPLICATED_STRATEGY = """
active_strategy_id: main
buzz_strategy_id: main
strategies:
  main:
    rules:
      - type: obv_trend
        effect: increase_score_on_pass
  main:
    rules:
      - type: minimum_price
        effect: block_on_fail
        min_price: 10
"""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("file_name", "content"),
    [
        ("technical.yaml", DUPLICATED_STRATEGY),
        ("technical.yaml", "strategies:\n  main:\n    rules:\n      - type: rsi_range\n        max_rsi: 70\n        max_rsi: 80\n"),
        ("technical.local.yaml", "active_strategy_id: [moderate\n"),
    ],
)
async def test_unreadable_yaml_is_rejected_and_names_its_file(template: Path, file_name: str, content: str) -> None:
    (template.parent / file_name).write_text(content, encoding="utf-8")

    with pytest.raises(yaml.YAMLError) as error:
        await YamlTechnicalSettingsRepository(template).load()

    assert f"Technical settings file: {template.parent / file_name}" in getattr(error.value, "__notes__", [])
