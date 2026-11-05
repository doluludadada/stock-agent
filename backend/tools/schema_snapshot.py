"""
Writes tests/fixtures/schema/version_<SCHEMA_VERSION>.json: every table the SQLModel classes declare at the code's
schema version, with each column's class, its type on SQLite and on PostgreSQL, the enum members it stores and whether
it takes NULL, and each table's primary key, unique constraints and foreign keys. tests/test_schema_snapshot.py compares
the classes with the snapshot of the current SCHEMA_VERSION, so a change to an existing table fails until an upgrade
step raises SCHEMA_VERSION.

    cd backend && uv run python tools/schema_snapshot.py

It refuses to rewrite the current version's snapshot while an existing table differs from it: that change needs an
upgrade step first. A new table needs none, so the snapshot takes it in.
"""

import importlib
import json
import pkgutil
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Enum, MetaData, Table, UniqueConstraint
from sqlalchemy.dialects import postgresql, sqlite
from sqlmodel import SQLModel

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "src"))

import c_infrastructure.database.models as models  # noqa: E402
from c_infrastructure.database.models.schema_version_dto import SCHEMA_VERSION  # noqa: E402

SNAPSHOT = BACKEND / "tests" / "fixtures" / "schema" / f"version_{SCHEMA_VERSION}.json"
STEP_NEEDED = "a change to an existing table needs an upgrade step: append one to UPGRADES, then regenerate the snapshot"
REGENERATE = "cd backend && uv run python tools/schema_snapshot.py"


def declared_tables() -> MetaData:
    """SQLModel's metadata after every module of c_infrastructure.database.models is imported, so it holds every table."""
    for module in pkgutil.iter_modules(models.__path__):
        importlib.import_module(f"{models.__name__}.{module.name}")

    return SQLModel.metadata


def column_layout(column: Column[Any]) -> dict[str, Any]:
    layout = {
        "class": type(column.type).__name__,
        "sqlite": column.type.compile(dialect=sqlite.dialect()),
        "postgresql": column.type.compile(dialect=postgresql.dialect()),
        "nullable": bool(column.nullable),
    }

    if isinstance(column.type, Enum):
        layout["members"] = list(column.type.enums)

    return layout


def table_layout(table: Table) -> dict[str, Any]:
    unique = [constraint.columns for constraint in table.constraints if isinstance(constraint, UniqueConstraint)]
    unique += [index.columns for index in table.indexes if index.unique]

    return {
        "columns": {column.name: column_layout(column) for column in table.columns},
        "primary_key": [column.name for column in table.primary_key.columns],
        "unique": sorted(sorted(column.name for column in columns) for columns in unique),
        "foreign_keys": sorted(
            [
                key.referred_table.name,
                sorted([element.parent.name, element.column.name] for element in key.elements),
                key.ondelete or "",
            ]
            for key in table.foreign_key_constraints
        ),
    }


def schema_snapshot(metadata: MetaData) -> dict[str, Any]:
    return {name: table_layout(table) for name, table in sorted(metadata.tables.items())}


def changed_tables(snapshot: dict[str, Any], declared: dict[str, Any]) -> list[str]:
    """Each table of the snapshot that the classes no longer declare, or declare differently, with what differs."""
    changed = []

    for name, layout in snapshot.items():
        if name not in declared:
            changed.append(f"{name} (removed)")
            continue

        columns = sorted(
            column
            for column in layout["columns"].keys() | declared[name]["columns"].keys()
            if layout["columns"].get(column) != declared[name]["columns"].get(column)
        )
        keys = [key for key in ("primary_key", "unique", "foreign_keys") if layout[key] != declared[name][key]]

        if columns or keys:
            changed.append(f"{name} ({', '.join([*(f'column {column}' for column in columns), *keys])})")

    return changed


def added_tables(snapshot: dict[str, Any], declared: dict[str, Any]) -> list[str]:
    return sorted(declared.keys() - snapshot.keys())


def snapshot_text(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True) + "\n"


def main() -> int:
    declared = schema_snapshot(declared_tables())

    if SNAPSHOT.exists() and (changed := changed_tables(json.loads(SNAPSHOT.read_text(encoding="utf-8")), declared)):
        print(f"{STEP_NEEDED}. Changed since version {SCHEMA_VERSION}: {'; '.join(changed)}. Nothing written.")
        return 1

    SNAPSHOT.write_text(snapshot_text(declared), encoding="utf-8")
    print(f"Wrote {SNAPSHOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
