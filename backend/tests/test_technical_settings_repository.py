"""Each owner's technical settings in the SQL tables, on a real SQLite file, read back the way another process would."""

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Update, insert, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col
from support.formulas import LATEST_PRICE, Json, arithmetic, compare, group, indicator, market, rule
from support.harness import harness_settings
from support.settings import shipped_config
from trading_stack import SilentLogger

from a_domain.rules.technical.strategy import TechnicalSettings, TechnicalStrategy
from a_domain.types.errors import TechnicalSettingsConflictError
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.technical_settings_dto import (
    TechnicalFormulaNodeDTO,
    TechnicalIndicatorDTO,
    TechnicalSettingsDTO,
)
from c_infrastructure.technical.sql_technical_settings_repository import SqlTechnicalSettingsRepository

pytestmark = pytest.mark.asyncio

SETTINGS = TypeAdapter(TechnicalSettings)
STRATEGY_FILES = Path(__file__).resolve().parents[2] / "config" / "strategies"
INITIAL = shipped_config().technical.initial_settings
OTHER_INITIAL = harness_settings()


def open_database(folder: Path) -> DatabaseConnector:
    """A connector to the SQLite file in folder: a second one on the same folder is another process."""
    return DatabaseConnector(config=shipped_config(folder), logger=SilentLogger())


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncIterator[DatabaseConnector]:
    connector = open_database(tmp_path)
    await connector.init_db()
    yield connector
    await connector.close()


@pytest_asyncio.fixture
async def other_process(tmp_path: Path, db: DatabaseConnector) -> AsyncIterator[SqlTechnicalSettingsRepository]:
    connector = open_database(tmp_path)
    yield SqlTechnicalSettingsRepository(connector)
    await connector.close()


def with_period(strategy: TechnicalStrategy, indicator_id: str, period: int) -> TechnicalStrategy:
    return replace(
        strategy, indicators=strategy.indicators | {indicator_id: replace(strategy.indicators[indicator_id], period=period)}
    )


def count_rows(folder: Path, table: str, owner_id: str) -> int:
    with sqlite3.connect(folder / "stock_agent.db") as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table} WHERE owner_id = ?", (owner_id,)).fetchone()[0]


# ------------------------------ Owner and revision ------------------------------ #


async def test_a_first_load_saves_the_initial_settings_at_revision_0_and_a_later_load_never_resets_them(db: DatabaseConnector) -> None:
    repository = SqlTechnicalSettingsRepository(db)

    first = await repository.load("alice", replace(INITIAL, revision=7))
    later = await repository.load("alice", OTHER_INITIAL)

    assert first == later == INITIAL
    assert first.revision == 0


async def test_a_save_from_the_revision_read_replaces_the_settings_and_counts_up(db: DatabaseConnector) -> None:
    repository = SqlTechnicalSettingsRepository(db)
    read = await repository.load("alice", INITIAL)
    edited = replace(read, active_strategy_id="aggressive", buzz_strategy_id="conservative")

    saved = await repository.save("alice", edited)

    assert saved == replace(edited, revision=1)
    assert await repository.load("alice", INITIAL) == saved
    assert (await repository.save("alice", saved)).revision == 2
    assert (await repository.load("alice", OTHER_INITIAL)).revision == 2


async def test_a_save_from_an_older_revision_is_refused_and_changes_nothing(db: DatabaseConnector) -> None:
    repository = SqlTechnicalSettingsRepository(db)
    read = await repository.load("alice", INITIAL)
    first = await repository.save("alice", replace(read, active_strategy_id="aggressive"))

    with pytest.raises(TechnicalSettingsConflictError):
        await repository.save("alice", replace(read, active_strategy_id="conservative", buzz_strategy_id="conservative"))

    assert await repository.load("alice", INITIAL) == first


async def test_a_save_for_an_owner_who_never_loaded_is_refused_and_creates_nothing(db: DatabaseConnector) -> None:
    repository = SqlTechnicalSettingsRepository(db)

    with pytest.raises(TechnicalSettingsConflictError):
        await repository.save("nobody", INITIAL)

    assert await repository.load("nobody", OTHER_INITIAL) == OTHER_INITIAL


async def test_of_two_saves_from_one_revision_in_two_processes_one_wins_and_the_other_changes_nothing(
    db: DatabaseConnector, other_process: SqlTechnicalSettingsRepository
) -> None:
    repository = SqlTechnicalSettingsRepository(db)
    read = await repository.load("alice", INITIAL)

    results = await asyncio.gather(
        repository.save("alice", replace(read, active_strategy_id="aggressive")),
        other_process.save("alice", replace(read, active_strategy_id="conservative")),
        return_exceptions=True,
    )

    [winner] = [result for result in results if isinstance(result, TechnicalSettings)]
    assert [type(result) for result in results if not isinstance(result, TechnicalSettings)] == [TechnicalSettingsConflictError]
    assert winner.revision == 1
    assert await repository.load("alice", INITIAL) == winner


async def test_each_owner_has_independent_settings(db: DatabaseConnector) -> None:
    repository = SqlTechnicalSettingsRepository(db)
    alice, bob = await repository.load("alice", INITIAL), await repository.load("bob", INITIAL)

    alice_saved = await repository.save(
        "alice", replace(alice, strategies=(with_period(alice.strategies[1], "ind_a", 37),), active_strategy_id="balanced")
    )

    assert await repository.load("bob", INITIAL) == bob == INITIAL
    bob_saved = await repository.save("bob", replace(bob, active_strategy_id="aggressive"))
    assert bob_saved.revision == 1
    assert await repository.load("alice", INITIAL) == alice_saved
    assert [strategy.strategy_id for strategy in alice_saved.strategies] == ["balanced"]


async def test_two_processes_loading_a_new_owner_at_once_save_the_initial_settings_once(
    tmp_path: Path, db: DatabaseConnector, other_process: SqlTechnicalSettingsRepository
) -> None:
    repository = SqlTechnicalSettingsRepository(db)
    owners = [f"owner_{number}" for number in range(5)]

    loads = await asyncio.gather(
        *(load for owner in owners for load in (repository.load(owner, INITIAL), other_process.load(owner, OTHER_INITIAL)))
    )

    for owner, mine, theirs in zip(owners, loads[::2], loads[1::2], strict=True):
        assert mine == theirs, owner
        assert mine in (INITIAL, OTHER_INITIAL)
        assert count_rows(tmp_path, "technical_settings", owner) == 1
        assert count_rows(tmp_path, "technical_strategies", owner) == len(mine.strategies)


# --------------------------------- Strategies --------------------------------- #


async def test_a_copy_of_a_built_in_strategy_changes_alone(db: DatabaseConnector) -> None:
    repository = SqlTechnicalSettingsRepository(db)
    read = await repository.load("alice", INITIAL)
    balanced = read.active_strategy
    copies = (
        replace(balanced, strategy_id="my_balanced", name="My Balanced"),
        replace(balanced, strategy_id="your_balanced", name="Your Balanced"),
    )
    with_copies = await repository.save(
        "alice", replace(read, strategies=(*read.strategies, *copies), active_strategy_id="my_balanced")
    )

    edited = await repository.save(
        "alice",
        replace(
            with_copies,
            strategies=tuple(
                with_period(strategy, "ind_b", 83) if strategy.strategy_id == "my_balanced" else strategy
                for strategy in with_copies.strategies
            ),
        ),
    )

    loaded = await repository.load("alice", INITIAL)
    assert loaded == edited
    assert {strategy.strategy_id: strategy.indicators["ind_b"].period for strategy in loaded.strategies} == {
        "conservative": 60,
        "balanced": 60,
        "aggressive": 60,
        "my_balanced": 83,
        "your_balanced": 60,
    }
    assert (loaded.active_strategy.strategy_id, loaded.active_strategy.required_bars) == ("my_balanced", 84)
    assert shipped_config().technical.built_in_strategies == INITIAL.strategies


async def test_saving_settings_never_changes_the_built_in_strategy_files(db: DatabaseConnector) -> None:
    files = {path.name: path.read_bytes() for path in STRATEGY_FILES.glob("*.json")}
    repository = SqlTechnicalSettingsRepository(db)
    read = await repository.load("alice", INITIAL)

    await repository.save("alice", replace(read, strategies=tuple(with_period(strategy, "ind_a", 37) for strategy in read.strategies)))

    assert {path.name: path.read_bytes() for path in STRATEGY_FILES.glob("*.json")} == files
    assert shipped_config().technical.built_in_strategies == INITIAL.strategies
    assert all(strategy.indicators["ind_a"].period == 37 for strategy in (await repository.load("alice", INITIAL)).strategies)


# --------------------------------- Round trip --------------------------------- #

CLOSE, VOLUME = market("close"), market("volume")

CUSTOM: Json = {
    "strategy_id": "custom",
    "name": "我的趨勢與成交量",
    "indicators": {
        "ind_a": {"kind": "sma", "period": 37},
        "ind_b": {"kind": "sma", "period": 83},
        "ind_c": {"kind": "volume_sma", "period": 25},
        "ind_d": {"kind": "rsi", "period": 9},
        "ind_e": {"kind": "macd", "fast": 8, "slow": 21, "signal": 5},
        "ind_f": {"kind": "bollinger", "period": 30, "std": 2.5},
        "ind_g": {"kind": "stochastic", "k_period": 14, "d_period": 5},
        "ind_h": {"kind": "adx", "period": 10},
        "ind_i": {"kind": "atr", "period": 7},
        "ind_j": {"kind": "obv", "period": 15},
        "ind_k": {"kind": "mfi", "period": 21},
        "ind_l": {"kind": "macd", "fast": 12, "slow": 26, "signal": 9},
    },
    "scoring": {"base_score": 40, "block_failure_penalty": 12, "failure_score_reduction": 3, "pass_score_increase": 8},
    "rules": [
        rule(
            "我的趨勢與成交量條件",
            group(
                "all",
                compare(indicator("ind_a"), "crosses_above", indicator("ind_b")),
                compare(VOLUME, "gt", arithmetic(indicator("ind_c", bars_ago=1), "multiply", 1.8)),
            ),
        ),
        rule(
            "Momentum",
            group(
                "any",
                group("all", compare(indicator("ind_d"), "gte", 50), compare(100, "gte", indicator("ind_d"))),
                group(
                    "all",
                    compare(indicator("ind_e", "line"), "gt", indicator("ind_l", "signal")),
                    compare(indicator("ind_e", "histogram"), "ne", 0),
                    group("any", compare(indicator("ind_e", "signal", 3), "lt", -0.25), compare(indicator("ind_l", "line"), "eq", 0)),
                ),
                compare(indicator("ind_g", "percent_k"), "crosses_below", indicator("ind_g", "percent_d")),
            ),
            "reduce_score_on_fail",
        ),
        rule(
            "Bands and trend",
            group(
                "all",
                compare(CLOSE, "lt", indicator("ind_f", "upper")),
                compare(CLOSE, "gt", indicator("ind_f", "lower")),
                compare(indicator("ind_f", "middle", 2), "lte", indicator("ind_f", "middle")),
                compare(indicator("ind_f", "bandwidth"), "lt", 0.1),
                compare(indicator("ind_f", "percent_b"), "lte", 0.9),
                compare(indicator("ind_h", "plus_di"), "gt", indicator("ind_h", "minus_di")),
                compare(indicator("ind_h", "adx"), "gte", 20),
            ),
            "increase_score_on_pass",
        ),
        rule(
            "Range, flow and price",
            group(
                "all",
                compare(arithmetic(arithmetic(market("high"), "subtract", market("low")), "divide", market("low")), "lt", 0.07),
                compare(indicator("ind_j"), "gt", indicator("ind_j", "moving_average", 1)),
                compare(indicator("ind_k"), "lt", 80),
                compare(arithmetic(indicator("ind_i"), "divide", CLOSE), "lte", 0.05),
                compare(LATEST_PRICE, "gte", arithmetic(market("open", 3), "add", -1.5)),
                compare(market("volume", 250), "gte", 0),
            ),
            "increase_score_on_pass",
        ),
    ],
}
"""Every node type, operator, market field, indicator kind and output, written out in full with no default left out."""


def settings_json() -> Json:
    built_ins = [
        json.loads((STRATEGY_FILES / f"{strategy_id}.json").read_text()) for strategy_id in ("conservative", "balanced", "aggressive")
    ]
    return {"active_strategy_id": "custom", "buzz_strategy_id": "aggressive", "strategies": [*built_ins, CUSTOM], "revision": 0}


def unused_formula_words() -> list[str]:
    text = json.dumps(CUSTOM)
    words = ["sma", "volume_sma", "rsi", "macd", "bollinger", "stochastic", "adx", "atr", "obv", "mfi"]
    words += ["latest_price", "market", "indicator", "arithmetic", "comparison", "group", "all", "any"]
    words += ["add", "subtract", "multiply", "divide", "gt", "gte", "lt", "lte", "eq", "ne", "crosses_above", "crosses_below"]
    words += ["open", "high", "low", "close", "volume", "value", "line", "signal", "histogram", "upper", "middle", "lower"]
    words += ["bandwidth", "percent_b", "percent_k", "percent_d", "adx", "plus_di", "minus_di", "moving_average"]
    words += ["block_on_fail", "reduce_score_on_fail", "increase_score_on_pass"]

    return [word for word in words if f'"{word}"' not in text]


async def test_settings_keep_every_formula_through_json_and_sql(tmp_path: Path, db: DatabaseConnector) -> None:
    assert unused_formula_words() == []
    document = settings_json()
    settings = SETTINGS.validate_json(json.dumps(document))
    await SqlTechnicalSettingsRepository(db).load("alice", settings)
    reopened = open_database(tmp_path)

    try:
        loaded = await SqlTechnicalSettingsRepository(reopened).load("alice", OTHER_INITIAL)
    finally:
        await reopened.close()

    returned = json.loads(SETTINGS.dump_json(loaded))
    assert returned["strategies"][3] == CUSTOM
    assert {key: value for key, value in returned.items() if key != "strategies"} == {
        "active_strategy_id": "custom",
        "buzz_strategy_id": "aggressive",
        "revision": 0,
    }
    assert SETTINGS.validate_python(returned) == SETTINGS.validate_python(document) == loaded


# ------------------------------- Database checks ------------------------------- #


def node_row(**columns: Any) -> dict[str, Any]:
    """A formula part of alice's balanced strategy's first rule, child of its root."""
    blank = dict.fromkeys(("operator", "constant", "field", "indicator_id", "output", "bars_ago"))
    return {"owner_id": "alice", "strategy_id": "balanced", "rule_position": 0, "position": 99, "parent_position": 0} | blank | columns


@pytest.mark.parametrize(
    ("table", "row"),
    [
        pytest.param(
            TechnicalFormulaNodeDTO,
            node_row(node="indicator", indicator_id="ind_z", output="value", bars_ago=0),
            id="indicator-the-strategy-lacks",
        ),
        pytest.param(
            TechnicalFormulaNodeDTO, node_row(node="market", field="close", bars_ago=0, parent_position=98), id="missing-parent"
        ),
        pytest.param(TechnicalFormulaNodeDTO, node_row(node="constant", constant=1.0, parent_position=None), id="second-root"),
        pytest.param(TechnicalFormulaNodeDTO, node_row(node="constant", constant=1.0, rule_position=99), id="missing-rule"),
        pytest.param(
            TechnicalIndicatorDTO,
            {"owner_id": "alice", "strategy_id": "missing", "indicator_id": "ind_a", "kind": "sma", "period": 20},
            id="indicator-of-a-missing-strategy",
        ),
    ],
)
async def test_the_database_refuses_rows_that_break_a_formula(db: DatabaseConnector, table: type, row: dict[str, Any]) -> None:
    repository = SqlTechnicalSettingsRepository(db)
    read = await repository.load("alice", INITIAL)

    with pytest.raises(IntegrityError):
        async with db.get_session() as session:
            await session.execute(insert(table), [row])
            await session.commit()

    assert await repository.load("alice", INITIAL) == read


def nodes_of(node: str) -> Update:
    return update(TechnicalFormulaNodeDTO).where(col(TechnicalFormulaNodeDTO.node) == node)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(nodes_of("market").values(field=None), id="market-without-field"),
        pytest.param(nodes_of("indicator").values(output=None), id="indicator-without-output"),
        pytest.param(nodes_of("constant").values(constant=None), id="constant-without-value"),
        pytest.param(nodes_of("comparison").values(operator=None), id="comparison-without-operator"),
        pytest.param(nodes_of("market").values(node="formula"), id="unknown-node"),
        pytest.param(update(TechnicalSettingsDTO).values(revision=-1), id="negative-revision"),
    ],
)
async def test_rows_the_domain_model_refuses_are_never_read_as_settings(db: DatabaseConnector, change: Update) -> None:
    """The tables leave these checks to the domain model, which validates every row it reads."""
    repository = SqlTechnicalSettingsRepository(db)
    await repository.load("alice", INITIAL)

    async with db.get_session() as session:
        await session.execute(change)
        await session.commit()

    with pytest.raises(ValidationError):
        await repository.load("alice", INITIAL)
