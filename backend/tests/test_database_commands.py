"""
The database commands (`just db-status`, `db-backup`, `db-migrate`, `db-restore`) on a real PostgreSQL database: what
they print, the backups they write, an upgrade that keeps every row, a second migrate and a failed one that change
nothing, and a restore that puts a backup back after backing the current database up. The code holds no upgrade step
yet, so the tests that migrate give it one of their own, from one version below the code's.
"""

import hashlib
import io
import re
from datetime import datetime, tzinfo
from pathlib import Path

import pytest
from rich.console import Console
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlmodel import SQLModel
from support.databases import ENVIRONMENT, database_snapshot, execute, open_database

import c_infrastructure.database.db_connector as db_connector
import c_infrastructure.database.models.schema_version_dto as schema_version
from c_infrastructure.database.db_connector import DatabaseCommandError, DatabaseConnector, OutdatedDatabaseError
from c_infrastructure.database.models.schema_version_dto import FIRST_SCHEMA_VERSION, SCHEMA_VERSION
from d_presentation.cli import database as commands, terminal

pytestmark = pytest.mark.asyncio

OLDER = SCHEMA_VERSION - 1
"""The schema version the tests' own upgrade step starts from."""

ROWS = (
    "INSERT INTO technical_settings (owner_id, active_strategy_id, revision) VALUES ('local', 'trend', 1)",
    "INSERT INTO ohlcv_data (stock_id, ts, open, high, low, close, volume) VALUES ('2330', '2026-11-03 06:00:00', 1, 2, 0.5, 1.5, 9)",
    "INSERT INTO watchlists (owner_id, stock_id, type, created_at) VALUES ('local', '2330', 'manual', '2026-11-03 06:00:00')",
    "INSERT INTO mock_cash (owner_id, current_cash, initial_cash, created_at, updated_at) "
    "VALUES ('local', 5, 5, '2026-11-03 06:00:00', '2026-11-03 06:00:00')",
)
"""An owner's settings, a cached bar, a watchlist entry and cash."""

HELD = {"mock_cash": 1, "ohlcv_data": 1, "schema_version": 1, "technical_settings": 1, "watchlists": 1}
"""The tables that hold a row after ROWS, and how many."""


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    """What the commands print."""
    printed = io.StringIO()
    monkeypatch.setattr(terminal, "console", Console(file=printed, width=250))
    return printed


async def raise_settings_revisions(connection: AsyncConnection) -> None:
    """The tests' upgrade step: a change to the rows of one table, which leaves every table as the code declares it."""
    await connection.execute(text("UPDATE technical_settings SET revision = revision + 10"))


async def stops_after_its_first_statement(connection: AsyncConnection) -> None:
    """The same step, stopped right after its first statement as a crash would stop it."""
    await raise_settings_revisions(connection)
    raise RuntimeError("the upgrade stopped after its first statement")


async def current_database(folder: Path) -> DatabaseConnector:
    """A database startup created, holding ROWS."""
    connector = open_database(folder)
    await connector.init_db()
    await execute(*ROWS)
    return connector


async def older_database(folder: Path, monkeypatch: pytest.MonkeyPatch, step: schema_version.UpgradeStep) -> DatabaseConnector:
    """A database of the version before the code's, holding ROWS, which `step` alone upgrades to the code's version."""
    connector = await current_database(folder)
    await execute(f"UPDATE schema_version SET version = {OLDER}")
    monkeypatch.setattr(schema_version, "FIRST_SCHEMA_VERSION", OLDER)
    monkeypatch.setattr(schema_version, "UPGRADES", (step,))
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


async def settings_rows() -> list[tuple[str, ...]]:
    """Each owner's settings as (active_strategy_id, owner_id, revision)."""
    return (await database_snapshot())["technical_settings"][1]


async def test_status_of_an_empty_database_says_it_is_new_and_creates_no_table(tmp_path: Path, output: io.StringIO) -> None:
    connector = open_database(tmp_path)

    try:
        assert await commands.status(connector) == 0
    finally:
        await connector.close()

    printed = output.getvalue()
    location = f"{ENVIRONMENT['DB_USER']}@{ENVIRONMENT['DB_HOST']}:{ENVIRONMENT['DB_PORT']}/{ENVIRONMENT['DB_NAME']}"
    assert f"Database:        {location}\n" in printed
    assert f"Schema version:  none (this code needs {SCHEMA_VERSION})" in printed
    assert f"New: the next start creates every table at version {SCHEMA_VERSION}." in printed
    assert await database_snapshot() == {}


async def test_status_of_an_older_database_names_the_pending_step_and_counts_every_table(
    tmp_path: Path, output: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = await older_database(tmp_path, monkeypatch, raise_settings_revisions)

    try:
        await commands.status(connector)
    finally:
        await connector.close()

    printed = output.getvalue()
    assert f"Schema version:  {OLDER} (this code needs {SCHEMA_VERSION})" in printed
    assert f"Pending step:    {OLDER} -> {SCHEMA_VERSION} raise_settings_revisions\n" in printed
    assert f"The database is at schema version {OLDER}, and this version of stock-agent needs {SCHEMA_VERSION}." in printed
    assert "Startup never upgrades a database.\nRemedy: run `just db-migrate`. It backs the database up into backups/" in printed
    rows = printed_rows(printed)
    assert {table: int(counts[0]) for table, counts in rows.items() if counts != ["0"]} == HELD
    assert rows.keys() == SQLModel.metadata.tables.keys()
    assert "password" not in printed.lower()


async def test_startup_refuses_an_older_database_names_the_migrate_command_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = await older_database(tmp_path, monkeypatch, raise_settings_revisions)
    before = await database_snapshot()

    try:
        with pytest.raises(OutdatedDatabaseError) as refused:
            await connector.init_db()
    finally:
        await connector.close()

    assert str(refused.value) == (
        f"The database is at schema version {OLDER}, and this version of stock-agent needs {SCHEMA_VERSION}. Startup never "
        "upgrades a database.\nRemedy: run `just db-migrate`. It backs the database up into backups/ first, then upgrades "
        "it in one transaction. `just db-status` shows the steps it runs."
    )
    assert await database_snapshot() == before
    assert backups(tmp_path) == []


async def test_migrate_backs_up_then_runs_the_pending_step_keeping_every_row(
    tmp_path: Path, output: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = await older_database(tmp_path, monkeypatch, raise_settings_revisions)
    before = await database_snapshot()

    try:
        assert await commands.migrate(connector) == 0
        await connector.init_db()
    finally:
        await connector.close()

    after = await database_snapshot()
    printed = output.getvalue()
    [backup] = backups(tmp_path)
    assert f"Backed up to {backup}\n" in printed
    assert f"Migrated from version {OLDER} to {SCHEMA_VERSION}:\n  {OLDER} -> {SCHEMA_VERSION} raise_settings_revisions\n" in printed
    assert after["schema_version"][1] == [(str(SCHEMA_VERSION),)]
    assert after["technical_settings"][1] == [("trend", "local", "11")]
    untouched = before.keys() - {"schema_version", "technical_settings"}
    assert after.keys() == before.keys()
    assert {table: after[table] for table in untouched} == {table: before[table] for table in untouched}
    assert printed_rows(printed) == {table: [str(len(rows)), str(len(rows))] for table, (_, rows) in before.items()}
    assert backup.parent == tmp_path / "backups"
    assert backup.name.startswith(f"{ENVIRONMENT['DB_NAME']}.")
    assert re.fullmatch(rf"\.\d{{8}}-\d{{6}}\.v{OLDER}\.dump", backup.name.removeprefix(ENVIRONMENT["DB_NAME"]))


async def test_the_backup_migrate_made_is_the_database_before_the_upgrade_and_only_its_owner_reads_it(
    tmp_path: Path, output: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = await older_database(tmp_path, monkeypatch, raise_settings_revisions)
    before = await database_snapshot()

    try:
        await commands.migrate(connector)
        [backup] = backups(tmp_path)
        assert await database_snapshot() != before
        await connector.restore(backup)
    finally:
        await connector.close()

    assert await database_snapshot() == before
    assert (backup.parent.stat().st_mode & 0o777, backup.stat().st_mode & 0o777) == (0o700, 0o600)


async def test_a_second_migrate_changes_nothing_and_makes_no_backup(
    tmp_path: Path, output: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = await older_database(tmp_path, monkeypatch, raise_settings_revisions)

    try:
        await commands.migrate(connector)
        upgraded = await database_snapshot()
        output.seek(0)
        output.truncate()
        assert await commands.migrate(connector) == 0
    finally:
        await connector.close()

    assert output.getvalue().strip() == f"Already at version {SCHEMA_VERSION}. Nothing to migrate, and no backup was made."
    assert await database_snapshot() == upgraded
    assert len(backups(tmp_path)) == 1


async def test_migrate_of_an_empty_database_says_it_is_new_and_makes_no_backup(tmp_path: Path, output: io.StringIO) -> None:
    connector = open_database(tmp_path)

    try:
        assert await commands.migrate(connector) == 0
    finally:
        await connector.close()

    assert f"The database is new: the next start creates every table at version {SCHEMA_VERSION}. Nothing to migrate." in (
        output.getvalue()
    )
    assert await database_snapshot() == {}
    assert backups(tmp_path) == []


async def test_a_failing_step_leaves_the_old_version_and_its_rows_and_names_the_step_and_the_backup(
    tmp_path: Path, output: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = await older_database(tmp_path, monkeypatch, stops_after_its_first_statement)
    before = await database_snapshot()

    try:
        with pytest.raises(DatabaseCommandError) as failed:
            await commands.migrate(connector)
    finally:
        await connector.close()

    [backup] = backups(tmp_path)
    message = str(failed.value)
    assert f"The upgrade step {OLDER} -> {SCHEMA_VERSION} stops_after_its_first_statement failed: RuntimeError" in message
    assert f"still at version {OLDER} with every row it had. Its backup from before the upgrade: {backup}" in message
    assert await database_snapshot() == before
    assert await settings_rows() == [("trend", "local", "1")]


async def test_an_older_database_whose_table_changed_is_refused_and_the_upgrade_rolls_back(
    tmp_path: Path, output: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = await older_database(tmp_path, monkeypatch, raise_settings_revisions)
    await execute("ALTER TABLE mops_quarter_eps ADD COLUMN trading_date DATE")
    before = await database_snapshot()

    try:
        with pytest.raises(DatabaseCommandError) as refused:
            await commands.migrate(connector)
    finally:
        await connector.close()

    message = str(refused.value)
    assert [line.split()[1] for line in message.splitlines() if line.startswith("  - ")] == ["mops_quarter_eps"]
    assert "columns no longer used: trading_date" in message
    assert f"The upgrade rolled back: the database is still at version {OLDER}" in message
    assert await database_snapshot() == before


@pytest.mark.parametrize("stamp", [0, FIRST_SCHEMA_VERSION - 1, SCHEMA_VERSION + 1])
async def test_migrate_refuses_a_version_no_step_reaches_and_makes_no_backup(tmp_path: Path, stamp: int, output: io.StringIO) -> None:
    connector = await current_database(tmp_path)
    await execute(f"UPDATE schema_version SET version = {stamp}")
    before = await database_snapshot()

    try:
        with pytest.raises(OutdatedDatabaseError, match=f"schema version is {stamp}, and this version of stock-agent needs"):
            await commands.migrate(connector)
    finally:
        await connector.close()

    assert backups(tmp_path) == []
    assert await database_snapshot() == before


class StoppedClock(datetime):
    """The same second, whenever it is asked."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> StoppedClock:
        return cls(2026, 11, 3, 6, 0, tzinfo=tz)


async def test_two_backups_in_one_second_get_two_files(tmp_path: Path, output: io.StringIO, monkeypatch: pytest.MonkeyPatch) -> None:
    connector = await current_database(tmp_path)
    monkeypatch.setattr(db_connector, "datetime", StoppedClock)

    try:
        await commands.backup(connector)
        await commands.backup(connector)
        first, second = backups(tmp_path)
        await execute("DELETE FROM technical_settings")
        await connector.restore(second)
    finally:
        await connector.close()

    assert f"Backed up to {first}\n" in output.getvalue() and f"Backed up to {second}\n" in output.getvalue()
    assert first.read_bytes().startswith(b"PGDMP") and second.read_bytes().startswith(b"PGDMP")
    assert await settings_rows() == [("trend", "local", "1")]


async def test_restore_puts_a_backup_back_after_backing_up_the_current_database(tmp_path: Path, output: io.StringIO) -> None:
    connector = await current_database(tmp_path)

    try:
        await commands.backup(connector)
        [backup] = backups(tmp_path)
        kept = digest(backup)
        await execute(
            "UPDATE technical_settings SET revision = 2",
            "INSERT INTO technical_settings (owner_id, active_strategy_id, revision) VALUES ('b', 'x', 7)",
        )
        changed = await database_snapshot()
        assert await commands.restore(connector, backup, confirmed=True) == 0
        [current] = [path for path in backups(tmp_path) if path != backup]
        restored = await settings_rows()
        await connector.restore(current)
    finally:
        await connector.close()

    printed = output.getvalue()
    assert f"Backed the current database up to {current}, then restored {backup}:" in printed
    assert "Current: startup opens it as it is." in printed
    assert printed_rows(printed)["technical_settings"] == ["1"]
    assert restored == [("trend", "local", "1")]
    assert digest(backup) == kept
    assert await database_snapshot() == changed


async def test_restore_without_yes_changes_nothing(tmp_path: Path, output: io.StringIO) -> None:
    connector = await current_database(tmp_path)

    try:
        await commands.backup(connector)
        [backup] = backups(tmp_path)
        await execute("UPDATE technical_settings SET revision = 2")
        before = await database_snapshot()
        assert await commands.restore(connector, backup, confirmed=False) == 1
    finally:
        await connector.close()

    assert "Run it again with --yes to go ahead. Nothing changed." in output.getvalue()
    assert await database_snapshot() == before
    assert backups(tmp_path) == [backup]


async def test_restore_refuses_a_file_pg_dump_did_not_write_and_a_missing_file(tmp_path: Path, output: io.StringIO) -> None:
    connector = await current_database(tmp_path)
    before = await database_snapshot()
    other = tmp_path / "stock_agent.v3.db"
    other.write_bytes(b"SQLite format 3\x00")

    try:
        with pytest.raises(DatabaseCommandError, match=r"stock_agent\.v3\.db is not a backup that pg_dump wrote\. Nothing changed\."):
            await commands.restore(connector, other, confirmed=True)

        with pytest.raises(DatabaseCommandError, match=r"There is no file at .*missing\.dump\. Nothing changed\."):
            await commands.restore(connector, tmp_path / "missing.dump", confirmed=True)
    finally:
        await connector.close()

    assert backups(tmp_path) == []
    assert await database_snapshot() == before


async def test_restore_into_a_database_without_a_table_makes_no_backup(tmp_path: Path, output: io.StringIO) -> None:
    connector = await current_database(tmp_path)

    try:
        await commands.backup(connector)
        [backup] = backups(tmp_path)
        await connector.close()
        await execute("DROP SCHEMA public CASCADE", "CREATE SCHEMA public")
        connector = open_database(tmp_path)
        await commands.restore(connector, backup, confirmed=True)
    finally:
        await connector.close()

    assert f"The database had no table, so no backup was made, then restored {backup}:" in output.getvalue()
    assert await settings_rows() == [("trend", "local", "1")]
    assert backups(tmp_path) == [backup]


async def test_a_backup_without_pg_dump_says_how_to_install_it_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: io.StringIO
) -> None:
    connector = await older_database(tmp_path, monkeypatch, raise_settings_revisions)
    before = await database_snapshot()
    monkeypatch.setenv("PATH", str(tmp_path / "no-programs"))

    try:
        with pytest.raises(DatabaseCommandError, match=r"pg_dump is not on PATH\. .*brew install libpq.*Nothing changed\."):
            await commands.migrate(connector)
    finally:
        await connector.close()

    assert backups(tmp_path) == []
    assert await database_snapshot() == before
