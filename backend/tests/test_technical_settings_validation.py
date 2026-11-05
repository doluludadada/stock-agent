"""What the technical settings refuse, and the built-in strategies the developer ships in config/strategies/."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError
from support.formulas import LATEST_PRICE, Json, arithmetic, compare, group, indicator, market, rule
from support.settings import shipped_config

from a_domain.rules.technical.strategy import TechnicalSettings, TechnicalStrategy

SETTINGS = TypeAdapter(TechnicalSettings)
STRATEGY_FILES = Path(__file__).resolve().parents[2] / "config" / "strategies"
CLOSE = market("close")
SMA_20 = {"ind_a": {"kind": "sma", "period": 20}}
MACD = {"ind_m": {"kind": "macd", "fast": 12, "slow": 26, "signal": 9}}


def strategy_document(strategy_id: str = "main", indicators: Json | None = None, condition: Json | None = None) -> Json:
    return {
        "strategy_id": strategy_id,
        "name": "Main",
        "indicators": SMA_20 if indicators is None else indicators,
        "scoring": {},
        "rules": [rule("Rule", condition or compare(CLOSE, "gt", indicator("ind_a")))],
    }


def settings_document(*strategies: Json, active: str = "main", buzz: str = "main") -> Json:
    return {"active_strategy_id": active, "buzz_strategy_id": buzz, "strategies": list(strategies or [strategy_document()])}


def test_the_document_the_refusals_start_from_is_valid() -> None:
    settings = SETTINGS.validate_python(settings_document())

    assert (settings.active_strategy.strategy_id, settings.revision) == ("main", 0)


@pytest.mark.parametrize(
    ("indicators", "condition"),
    [
        pytest.param(SMA_20, compare(CLOSE, "gt", indicator("ind_z")), id="unknown-indicator-id"),
        pytest.param(SMA_20, compare(CLOSE, "gt", indicator("ind_a", "signal")), id="sma-has-no-signal"),
        pytest.param(MACD, compare(indicator("ind_m"), "gt", 0), id="macd-has-no-value"),
        pytest.param(SMA_20, compare(CLOSE, "gt", indicator("ind_a", "average")), id="unknown-output"),
        pytest.param(SMA_20, compare(LATEST_PRICE, "crosses_above", indicator("ind_a")), id="crossing-of-the-latest-price"),
        pytest.param(
            SMA_20,
            compare(indicator("ind_a"), "crosses_below", arithmetic(LATEST_PRICE, "multiply", 1.1)),
            id="crossing-of-a-latest-price-part",
        ),
        pytest.param(SMA_20, compare(20, "gt", 10), id="two-constants"),
        pytest.param(SMA_20, compare(arithmetic(1, "add", 2), "gt", 0), id="constant-arithmetic"),
        pytest.param(SMA_20, group("all"), id="empty-group"),
        pytest.param(SMA_20, group("any", group("all")), id="empty-nested-group"),
        pytest.param(SMA_20, compare(CLOSE, "gt", "1.8"), id="string-constant"),
        pytest.param(SMA_20, compare(CLOSE, "gt", True), id="boolean-constant"),
        pytest.param(SMA_20, compare(CLOSE, "gt", group("all", compare(CLOSE, "gt", 1))), id="condition-as-a-number"),
        pytest.param(SMA_20, compare(arithmetic(CLOSE, "multiply", compare(CLOSE, "gt", 1)), "gt", 1), id="condition-in-arithmetic"),
        pytest.param(SMA_20, compare(CLOSE, "gt", float("nan")), id="nan-constant"),
        pytest.param(SMA_20, compare(CLOSE, "gt", float("inf")), id="infinite-constant"),
        pytest.param(SMA_20, compare(market("close", -1), "gt", 0), id="negative-bars-ago"),
        pytest.param(SMA_20, compare(market("close", 251), "gt", 0), id="bars-ago-over-250"),
        pytest.param(SMA_20, compare(indicator("ind_a", bars_ago=251), "gt", 0), id="indicator-bars-ago-over-250"),
        pytest.param(SMA_20, compare(market("close", True), "gt", 0), id="boolean-bars-ago"),
        pytest.param(SMA_20, compare(market("close", "1"), "gt", 0), id="string-bars-ago"),
        pytest.param(SMA_20, compare(market("turnover"), "gt", 0), id="unknown-market-field"),
        pytest.param(SMA_20, compare(CLOSE, "approximately", 10), id="unknown-comparison"),
        pytest.param(SMA_20, compare(arithmetic(CLOSE, "power", 2), "gt", 0), id="unknown-arithmetic"),
        pytest.param(SMA_20, group("most", compare(CLOSE, "gt", 1)), id="unknown-group-operator"),
        pytest.param(SMA_20, {"type": "formula", "text": "close > 10"}, id="unknown-node"),
        pytest.param(SMA_20, compare(market("volume") | {"unit": "lots"}, "gt", 500), id="unknown-node-field"),
        pytest.param({"ind_a": {"kind": "sma", "period": 0}}, None, id="period-0"),
        pytest.param({"ind_a": {"kind": "sma", "period": 501}}, None, id="period-over-500"),
        pytest.param({"ind_a": {"kind": "sma", "period": "20"}}, None, id="string-period"),
        pytest.param({"ind_a": {"kind": "sma", "period": True}}, None, id="boolean-period"),
        pytest.param({"ind_a": {"kind": "sma", "period": 20.5}}, None, id="fractional-period"),
        pytest.param({"ind_a": {"kind": "sma"}}, None, id="missing-period"),
        pytest.param({"ind_a": {"kind": "sma", "period": 20, "std": 2.0}}, None, id="parameter-of-another-kind"),
        pytest.param({"ind_a": {"kind": "wma", "period": 20}}, None, id="unknown-kind"),
        pytest.param({"ind_a": {"kind": "bollinger", "period": 20, "std": "2"}}, None, id="string-std"),
        pytest.param({"ind_a": {"kind": "bollinger", "period": 20, "std": 0}}, None, id="zero-std"),
        pytest.param(
            {"MA60": {"kind": "sma", "period": 60}}, compare(CLOSE, "gt", indicator("MA60")), id="indicator-id-not-a-formula-id"
        ),
        pytest.param(
            {"ind_m": {"kind": "macd", "fast": 26, "slow": 12, "signal": 9}},
            compare(indicator("ind_m", "line"), "gt", 0),
            id="macd-fast-slower-than-slow",
        ),
        pytest.param(
            {"ind_m": {"kind": "macd", "fast": 12, "slow": 12, "signal": 9}},
            compare(indicator("ind_m", "line"), "gt", 0),
            id="macd-fast-equal-to-slow",
        ),
    ],
)
def test_an_invalid_indicator_or_formula_is_refused(indicators: Json, condition: Json | None) -> None:
    document = settings_document(strategy_document(indicators=indicators, condition=condition))

    with pytest.raises(ValidationError):
        SETTINGS.validate_python(document)


@pytest.mark.parametrize(
    ("indicators", "condition"),
    [
        pytest.param({"ind_a": {"kind": "sma", "period": 500}}, None, id="period-500"),
        pytest.param({"ind_a": {"kind": "sma", "period": 1}}, None, id="period-1"),
        pytest.param(SMA_20, compare(indicator("ind_a", bars_ago=250), "gt", market("close", 250)), id="bars-ago-250"),
        pytest.param(SMA_20, compare(CLOSE, "crosses_above", 10), id="crossing-a-constant"),
        pytest.param(SMA_20, compare(LATEST_PRICE, "gte", 15), id="latest-price-against-a-constant"),
        pytest.param({**SMA_20, "ind_b": {"kind": "rsi", "period": 14}}, None, id="unread-indicator"),
        pytest.param(
            {"ind_m": {"kind": "macd", "fast": 25, "slow": 26, "signal": 1}},
            compare(indicator("ind_m", "histogram"), "gt", 0),
            id="macd-fast-one-shorter",
        ),
    ],
)
def test_values_at_the_edge_of_the_bounds_are_accepted(indicators: Json, condition: Json | None) -> None:
    SETTINGS.validate_python(settings_document(strategy_document(indicators=indicators, condition=condition)))


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(settings_document(strategy_document(), strategy_document()), id="duplicate-strategy-id"),
        pytest.param(settings_document(active="missing"), id="missing-active-strategy"),
        pytest.param(settings_document(buzz="missing"), id="missing-buzz-strategy"),
        pytest.param({"active_strategy_id": "main", "buzz_strategy_id": "main", "strategies": []}, id="no-strategies"),
        pytest.param(settings_document(strategy_document() | {"rules": []}), id="strategy-without-rules"),
        pytest.param(settings_document(strategy_document() | {"name": " "}), id="blank-strategy-name"),
        pytest.param(
            settings_document(strategy_document("Main Strategy"), active="Main Strategy", buzz="Main Strategy"),
            id="strategy-id-not-a-formula-id",
        ),
        pytest.param(settings_document() | {"revision": -1}, id="negative-revision"),
        pytest.param(settings_document(strategy_document() | {"scoring": {"base_score": 101}}), id="base-score-over-100"),
    ],
)
def test_invalid_settings_are_refused(document: Json) -> None:
    with pytest.raises(ValidationError):
        SETTINGS.validate_python(document)


# ---------------------------- Built-in strategies ---------------------------- #


def built_in_file(strategy_id: str) -> Any:
    return (STRATEGY_FILES / f"{strategy_id}.json").read_bytes()


@pytest.mark.parametrize(("strategy_id", "rule_count"), [("conservative", 23), ("balanced", 23), ("aggressive", 20)])
def test_each_built_in_strategy_file_is_a_valid_strategy_that_needs_61_bars(strategy_id: str, rule_count: int) -> None:
    strategy = TypeAdapter(TechnicalStrategy).validate_json(built_in_file(strategy_id))

    assert (strategy.strategy_id, len(strategy.rules), strategy.required_bars) == (strategy_id, rule_count, 61)


def test_the_built_in_strategies_are_the_three_files_in_menu_order_and_every_owner_starts_on_balanced() -> None:
    technical = shipped_config().technical
    initial = technical.initial_settings

    assert sorted(path.stem for path in STRATEGY_FILES.glob("*.json")) == ["aggressive", "balanced", "conservative"]
    assert [strategy.strategy_id for strategy in technical.built_in_strategies] == ["conservative", "balanced", "aggressive"]
    assert (initial.active_strategy_id, initial.buzz_strategy_id, initial.revision) == ("balanced", "balanced", 0)
    assert initial.strategies == technical.built_in_strategies
