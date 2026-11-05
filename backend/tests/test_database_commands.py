"""
The database commands (`just db-status`, `db-backup`, `db-migrate`, `db-restore`) on a real database of each backend:
what they print, the backups they write, an upgrade that keeps every row, a second migrate and a failed one that change
nothing, and a restore that puts a backup back after backing the current database up.
"""

import hashlib
import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from rich.console import Console
from sqlalchemy import text
from support.databases import BACKENDS, create_version_1_tables, database_config, database_snapshot, empty_database, raw_engine
from trading_stack import SilentLogger

import c_infrastructure.database.models.schema_version_dto as schema_version
from a_domain.types.enums import DatabaseBackend
from c_infrastructure.database.db_connector import DatabaseCommandError, DatabaseConnector, OutdatedDatabaseError
from c_infrastructure.database.models.schema_version_dto import SCHEMA_VERSION
from d_presentation.cli import database as commands, terminal

pytestmark = pytest.mark.asyncio

AT = datetime(2026, 11, 3, 6, 0)

# fmt: off
VERSION_1_ROWS: list[tuple[str, dict[str, Any]]] = [
    (
        "workflow_runs",
        {
            "run_id": UUID(int=1), "workflow": "FULL_CYCLE", "execution_provider": "MOCK", "order_mode": "MOCK_ONLY",
            "start_time": AT, "end_time": AT, "total_scanned": 3, "buzz_scanned": 0, "buzz_qualified": 0,
            "sentiment_analysed": 0, "passed_technical": 1, "ai_analysed": 1, "signals_generated": 1,
            "orders_submitted": 0, "orders_filled": 0, "orders_refused": 0, "stale_market_data_count": 0,
            "errors": '["Run aborted: RuntimeError: Yahoo hung"]', "execution_log": "[]",
        },
    ),
    ("ohlcv_data", {"stock_id": "2330", "ts": AT, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 9}),
    ("watchlists", {"stock_id": "2330", "type": "manual", "created_at": AT, "expires_at": None}),
    ("mock_cash", {"account_id": "mock-dev", "current_cash": 5.0, "initial_cash": 5.0, "created_at": AT, "updated_at": AT}),
    ("technical_settings", {"owner_id": "local", "active_strategy_id": "trend", "buzz_strategy_id": "buzz", "revision": 4}),
]
# fmt: on


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    """What the commands print."""
    printed = io.StringIO()
    monkeypatch.setattr(terminal, "console", Console(file=printed, width=250))
    return printed


def bound(backend: DatabaseBackend, value: Any) -> Any:
    """A value as the backend's driver takes it in raw SQL: SQLite keeps UUIDs as 32 hex digits and datetimes as text."""
    if backend == DatabaseBackend.SQLITE and isinstance(value, UUID):
        return value.hex

    if backend == DatabaseBackend.SQLITE and isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="microseconds")

    return value


async def execute(backend: DatabaseBackend, folder: Path, *statements: str) -> None:
    engine = raw_engine(backend, folder)

    async with engine.begin() as connection:
        for statement in statements:
            await connection.execute(text(statement))

    await engine.dispose()


async def version_1_database(backend: DatabaseBackend, folder: Path) -> DatabaseConnector:
    """A version 1 database, from the tables a version 1 app wrote, with a run, a cached bar, a watchlist entry, cash and settings."""
    connector = await empty_database(backend, folder)
    await create_version_1_tables(backend, folder)
    engine = raw_engine(backend, folder)

    async with engine.begin() as connection:
        for table, row in VERSION_1_ROWS:
            await connection.execute(
                text(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join(f':{column}' for column in row)})"),
                {column: bound(backend, value) for column, value in row.items()},
            )

    await engine.dispose()
    return connector


async def current_database(backend: DatabaseBackend, folder: Path) -> DatabaseConnector:
    """A database startup created, holding one owner's settings row."""
    connector = await empty_database(backend, folder)
    await connector.init_db()
    await execute(backend, folder, "INSERT INTO technical_settings VALUES ('local', 'trend', 'buzz', 1)")
    return connector


def printed_rows(printed: str) -> dict[str, list[str]]:
    """The row-count lines a command printed: table name, then one count per column."""
    return {
        name: counts
        for line in printed.splitlines()
        if (words := line.split()) and len(words) >= 2 and re.fullmatch(r"[a-z_]+", (name := words[0]))
        for counts in [words[1:]]
        if all(re.fullmatch(r"\d+|-", count) for count in counts)
    }


def backups(folder: Path) -> list[Path]:
    return sorted((folder / "backups").glob("*")) if (folder / "backups").exists() else []


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def test_status_of_a_missing_sqlite_file_says_it_is_new_and_creates_no_file(tmp_path: Path, output: io.StringIO) -> None:
    connector = await empty_database(DatabaseBackend.SQLITE, tmp_path)

    try:
        assert await commands.status(connector) == 0
    finally:
        await connector.close()

    printed = output.getvalue()
    assert f"Database:        sqlite {tmp_path / 'stock_agent.db'}" in printed
    assert f"Schema version:  none (this code needs {SCHEMA_VERSION})" in printed
    assert f"New: the next start creates every table at version {SCHEMA_VERSION}." in printed
    assert not (tmp_path / "stock_agent.db").exists()


@pytest.mark.parametrize("backend", BACKENDS)
async def test_status_of_a_version_1_database_names_the_pending_steps_and_counts_every_table(
    backend: DatabaseBackend, tmp_path: Path, output: io.StringIO
) -> None:
    connector = await version_1_database(backend, tmp_path)

    try:
        await commands.status(connector)
    finally:
        await connector.close()

    printed = output.getvalue()
    assert f"Schema version:  1 (this code needs {SCHEMA_VERSION})" in printed
    assert "Pending step:    1 -> 2 record_run_failures\nPending step:    2 -> 3 give_rows_their_owner" in printed
    assert f"The database is at schema version 1, and this version of stock-agent needs {SCHEMA_VERSION}." in printed
    assert "Startup never upgrades a database.\nRemedy: run `just db-migrate`. It backs the database up into backups/" in printed
    rows = printed_rows(printed)
    assert {table: counts for table, counts in rows.items() if counts != ["0"]} == {
        "ohlcv_data": ["1"],
        "mock_cash": ["1"],
        "schema_version": ["1"],
        "technical_settings": ["1"],
        "watchlists": ["1"],
        "workflow_runs": ["1"],
    }
    assert len(rows) == 19
    assert "password" not in printed.lower()


@pytest.mark.parametrize("backend", BACKENDS)
async def test_startup_refuses_an_older_database_names_the_migrate_command_and_changes_nothing(
    backend: DatabaseBackend, tmp_path: Path
) -> None:
    connector = await version_1_database(backend, tmp_path)
    before = await database_snapshot(backend, tmp_path)

    try:
        with pytest.raises(OutdatedDatabaseError) as refused:
            await connector.init_db()
    finally:
        await connector.close()

    assert str(refused.value) == (
        f"The database is at schema version 1, and this version of stock-agent needs {SCHEMA_VERSION}. Startup never "
        "upgrades a database.\nRemedy: run `just db-migrate`. It backs the database up into backups/ first, then upgrades "
        "it in one transaction. `just db-status` shows the steps it runs."
    )
    assert await database_snapshot(backend, tmp_path) == before
    assert backups(tmp_path) == []


@pytest.mark.parametrize("backend", BACKENDS)
async def test_migrate_backs_up_then_upgrades_version_1_keeping_every_row(
    backend: DatabaseBackend, tmp_path: Path, output: io.StringIO
) -> None:
    connector = await version_1_database(backend, tmp_path)
    before = await database_snapshot(backend, tmp_path)

    try:
        assert await commands.migrate(connector) == 0
    finally:
        await connector.close()

    after = await database_snapshot(backend, tmp_path)
    printed = output.getvalue()
    [backup] = backups(tmp_path)
    assert f"Backed up to {backup}" in printed
    assert f"Migrated from version 1 to {SCHEMA_VERSION}:\n  1 -> 2 record_run_failures\n  2 -> 3 give_rows_their_owner" in printed
    assert after["schema_version"][1] == [(str(SCHEMA_VERSION),)]
    assert {table: len(rows) for table, (_, rows) in after.items() if table in before} == {
        table: len(rows) for table, (_, rows) in before.items()
    }
    assert {table: counts for table, counts in printed_rows(printed).items() if table in before} == {
        table: [str(len(rows)), str(len(rows))] for table, (_, rows) in before.items()
    }
    runs = after["workflow_runs"]
    assert [row[runs[0].index("failure")] for row in runs[1]] == ["RuntimeError: Yahoo hung"]
    assert backup.parent == tmp_path / "backups"
    assert re.fullmatch(r"[a-z_]+\.\d{8}-\d{6}\.v1\.(db|dump)", backup.name)


async def test_the_sqlite_backup_is_the_database_before_the_upgrade(tmp_path: Path, output: io.StringIO) -> None:
    connector = await version_1_database(DatabaseBackend.SQLITE, tmp_path)
    before = await database_snapshot(DatabaseBackend.SQLITE, tmp_path)

    try:
        await commands.migrate(connector)
    finally:
        await connector.close()

    [backup] = backups(tmp_path)
    (tmp_path / "copy").mkdir()
    (tmp_path / "copy" / "stock_agent.db").write_bytes(backup.read_bytes())
    assert await database_snapshot(DatabaseBackend.SQLITE, tmp_path / "copy") == before
    assert (backup.parent.stat().st_mode & 0o777, backup.stat().st_mode & 0o777) == (0o700, 0o600)


@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_second_migrate_changes_nothing_and_makes_no_backup(
    backend: DatabaseBackend, tmp_path: Path, output: io.StringIO
) -> None:
    connector = await version_1_database(backend, tmp_path)

    try:
        await commands.migrate(connector)
        upgraded = await database_snapshot(backend, tmp_path)
        output.seek(0)
        output.truncate()
        assert await commands.migrate(connector) == 0
    finally:
        await connector.close()

    assert output.getvalue().strip() == f"Already at version {SCHEMA_VERSION}. Nothing to migrate, and no backup was made."
    assert await database_snapshot(backend, tmp_path) == upgraded
    assert len(backups(tmp_path)) == 1


async def crashes_after_its_first_statement(connection: Any) -> None:
    """The version 2 to 3 step, stopped right after its first statement as a crash would stop it."""

    class FailsAfterFirstStatement:
        dialect = connection.dialect
        statements = 0

        async def execute(self, *args: Any, **kwargs: Any) -> Any:
            if self.statements == 1:
                raise RuntimeError("the upgrade stopped after its first statement")

            self.statements += 1
            return await connection.execute(*args, **kwargs)

    await schema_version.give_rows_their_owner(FailsAfterFirstStatement())


@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_failing_step_leaves_the_old_version_and_its_rows_and_names_the_step_and_the_backup(
    backend: DatabaseBackend, tmp_path: Path, output: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = await version_1_database(backend, tmp_path)
    before = await database_snapshot(backend, tmp_path)
    monkeypatch.setattr(schema_version, "UPGRADES", (schema_version.record_run_failures, crashes_after_its_first_statement))

    try:
        with pytest.raises(DatabaseCommandError) as failed:
            await commands.migrate(connector)
    finally:
        await connector.close()

    [backup] = backups(tmp_path)
    message = str(failed.value)
    assert "The upgrade step 2 -> 3 crashes_after_its_first_statement failed: RuntimeError" in message
    assert f"still at version 1 with every row it had. Its backup from before the upgrade: {backup}" in message
    assert await database_snapshot(backend, tmp_path) == before


@pytest.mark.parametrize("stamp", [0, SCHEMA_VERSION + 1])
async def test_migrate_refuses_a_version_no_step_reaches_and_makes_no_backup(tmp_path: Path, stamp: int, output: io.StringIO) -> None:
    connector = await current_database(DatabaseBackend.SQLITE, tmp_path)
    await execute(DatabaseBackend.SQLITE, tmp_path, f"UPDATE schema_version SET version = {stamp}")
    before = await database_snapshot(DatabaseBackend.SQLITE, tmp_path)

    try:
        with pytest.raises(OutdatedDatabaseError, match=f"schema version is {stamp}, and this version of stock-agent needs"):
            await commands.migrate(connector)
    finally:
        await connector.close()

    assert backups(tmp_path) == []
    assert await database_snapshot(DatabaseBackend.SQLITE, tmp_path) == before


async def test_two_backups_in_one_second_get_two_files(tmp_path: Path, output: io.StringIO) -> None:
    connector = await current_database(DatabaseBackend.SQLITE, tmp_path)

    try:
        await commands.backup(connector)
        await commands.backup(connector)
    finally:
        await connector.close()

    first, second = backups(tmp_path)
    assert f"Backed up to {first}" in output.getvalue() and f"Backed up to {second}" in output.getvalue()
    assert first.read_bytes() == second.read_bytes()


async def settings_rows(backend: DatabaseBackend, folder: Path) -> list[tuple[str, ...]]:
    return (await database_snapshot(backend, folder))["technical_settings"][1]


@pytest.mark.parametrize("backend", BACKENDS)
async def test_restore_puts_a_backup_back_after_backing_up_the_current_database(
    backend: DatabaseBackend, tmp_path: Path, output: io.StringIO
) -> None:
    connector = await current_database(backend, tmp_path)

    try:
        await commands.backup(connector)
        [backup] = backups(tmp_path)
        kept = digest(backup)
        await execute(
            backend, tmp_path, "UPDATE technical_settings SET revision = 2", "INSERT INTO technical_settings VALUES ('b', 'x', 'y', 7)"
        )
        changed = await database_snapshot(backend, tmp_path)
        assert await commands.restore(connector, backup, confirmed=True) == 0
    finally:
        await connector.close()

    [current] = [path for path in backups(tmp_path) if path != backup]
    printed = output.getvalue()
    assert f"Backed the current database up to {current}, then restored {backup}:" in printed
    assert "Current: startup opens it as it is." in printed
    assert printed_rows(printed)["technical_settings"] == ["1"]
    assert await settings_rows(backend, tmp_path) == [("trend", "buzz", "local", "1")]
    assert digest(backup) == kept

    if backend == DatabaseBackend.SQLITE:
        (tmp_path / "copy").mkdir()
        (tmp_path / "copy" / "stock_agent.db").write_bytes(current.read_bytes())
        assert await database_snapshot(backend, tmp_path / "copy") == changed


async def test_restore_without_yes_changes_nothing(tmp_path: Path, output: io.StringIO) -> None:
    connector = await current_database(DatabaseBackend.SQLITE, tmp_path)

    try:
        await commands.backup(connector)
        [backup] = backups(tmp_path)
        await execute(DatabaseBackend.SQLITE, tmp_path, "UPDATE technical_settings SET revision = 2")
        before = await database_snapshot(DatabaseBackend.SQLITE, tmp_path)
        assert await commands.restore(connector, backup, confirmed=False) == 1
    finally:
        await connector.close()

    assert "Run it again with --yes to go ahead. Nothing changed." in output.getvalue()
    assert await database_snapshot(DatabaseBackend.SQLITE, tmp_path) == before
    assert backups(tmp_path) == [backup]


@pytest.mark.parametrize("backend", BACKENDS)
async def test_restore_refuses_a_file_that_is_not_a_backup_of_the_backend(
    backend: DatabaseBackend, tmp_path: Path, output: io.StringIO
) -> None:
    connector = await current_database(backend, tmp_path)
    before = await database_snapshot(backend, tmp_path)
    other = tmp_path / ("stock_agent.v3.db" if backend == DatabaseBackend.POSTGRESQL else "stock_agent.v3.dump")
    other.write_bytes(b"PGDMP\x01" if backend == DatabaseBackend.SQLITE else b"SQLite format 3\x00")

    try:
        with pytest.raises(DatabaseCommandError, match=f"is not a backup of a {backend.value} database. Nothing changed."):
            await commands.restore(connector, other, confirmed=True)

        with pytest.raises(DatabaseCommandError, match="There is no file at .*missing.db. Nothing changed."):
            await commands.restore(connector, tmp_path / "missing.db", confirmed=True)
    finally:
        await connector.close()

    assert backups(tmp_path) == []
    assert await database_snapshot(backend, tmp_path) == before


async def test_restore_brings_back_a_deleted_sqlite_database(tmp_path: Path, output: io.StringIO) -> None:
    connector = await current_database(DatabaseBackend.SQLITE, tmp_path)

    try:
        await commands.backup(connector)
        [backup] = backups(tmp_path)
        await connector.close()
        (tmp_path / "stock_agent.db").unlink()
        connector = DatabaseConnector(config=database_config(DatabaseBackend.SQLITE, tmp_path), logger=SilentLogger())
        await commands.restore(connector, backup, confirmed=True)
    finally:
        await connector.close()

    assert f"The database had no table, so no backup was made, then restored {backup}:" in output.getvalue()
    assert await settings_rows(DatabaseBackend.SQLITE, tmp_path) == [("trend", "buzz", "local", "1")]
    assert backups(tmp_path) == [backup]


@pytest.mark.parametrize("backend", [param for param in BACKENDS if param.id == "postgresql"])
async def test_a_backup_without_pg_dump_says_how_to_install_it_and_changes_nothing(
    backend: DatabaseBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: io.StringIO
) -> None:
    connector = await version_1_database(backend, tmp_path)
    before = await database_snapshot(backend, tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "no-programs"))

    try:
        with pytest.raises(DatabaseCommandError, match=r"pg_dump is not on PATH\. .*brew install libpq.*Nothing changed\."):
            await commands.migrate(connector)
    finally:
        await connector.close()

    assert backups(tmp_path) == []
    assert await database_snapshot(backend, tmp_path) == before
