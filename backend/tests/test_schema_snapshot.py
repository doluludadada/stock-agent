"""
A change to an existing table needs an upgrade step: the SQLModel classes must match the committed snapshot of the
current SCHEMA_VERSION (tests/fixtures/schema/version_<N>.json, written by tools/schema_snapshot.py). A new table needs
no step, because startup creates it, but the snapshot must take it in.
"""

import json
from typing import Any

import pytest
from schema_snapshot import REGENERATE, SNAPSHOT, STEP_NEEDED, added_tables, changed_tables, declared_tables, schema_snapshot
from sqlalchemy import Column, Date, Enum, Integer, MetaData, String, Table

from c_infrastructure.database.models.schema_version_dto import SCHEMA_VERSION


@pytest.fixture(scope="module")
def committed() -> dict[str, Any]:
    if not SNAPSHOT.exists():
        pytest.fail(f"No snapshot of schema version {SCHEMA_VERSION}, which an upgrade step raised it to: {REGENERATE}")

    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_every_existing_table_is_as_the_snapshot_of_the_current_version_has_it(committed: dict[str, Any]) -> None:
    changed = changed_tables(committed, schema_snapshot(declared_tables()))

    assert not changed, f"{STEP_NEEDED} ({REGENERATE}). Changed since version {SCHEMA_VERSION}: {'; '.join(changed)}"


def test_the_snapshot_holds_every_new_table(committed: dict[str, Any]) -> None:
    added = added_tables(committed, schema_snapshot(declared_tables()))

    assert not added, (
        f"A new table needs no upgrade step, because startup creates it, but regenerate the snapshot ({REGENERATE}): {added}"
    )


def declared_copy() -> MetaData:
    copy = MetaData()

    for table in declared_tables().tables.values():
        table.to_metadata(copy)

    return copy


@pytest.mark.parametrize(
    ("change", "found"),
    [
        pytest.param(
            lambda tables: tables["ohlcv_data"].append_column(Column("trading_date", Date())),
            "ohlcv_data (column trading_date)",
            id="added column",
        ),
        pytest.param(
            lambda tables: setattr(tables["watchlists"].c.expires_at, "nullable", False),
            "watchlists (column expires_at)",
            id="nullability",
        ),
        pytest.param(
            lambda tables: setattr(tables["mock_cash"].c.current_cash, "type", Integer()), "mock_cash (column current_cash)", id="type"
        ),
        pytest.param(
            lambda tables: setattr(
                tables["orders"].c.status, "type", Enum(*tables["orders"].c.status.type.enums, "HELD", name="orderstatus")
            ),
            "orders (column status)",
            id="enum member",
        ),
        pytest.param(
            lambda tables: tables["ohlcv_fetches"].metadata.remove(tables["ohlcv_fetches"]),
            "ohlcv_fetches (removed)",
            id="removed table",
        ),
    ],
)
def test_the_guard_names_a_changed_existing_table(change: Any, found: str) -> None:
    changed = declared_copy()
    change(changed.tables)

    assert changed_tables(schema_snapshot(declared_tables()), schema_snapshot(changed)) == [found]


def test_the_guard_passes_an_added_table_and_asks_for_the_snapshot() -> None:
    changed = declared_copy()
    Table("snapshot_guard_probe", changed, Column("probe_id", String(), primary_key=True))
    declared, with_new_table = schema_snapshot(declared_tables()), schema_snapshot(changed)

    assert changed_tables(declared, with_new_table) == []
    assert added_tables(declared, with_new_table) == ["snapshot_guard_probe"]
