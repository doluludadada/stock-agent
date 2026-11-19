"""
The database commands (`just db-status`, `db-backup`, `db-migrate`, `db-restore`) on a real PostgreSQL database: what
they print, the backups they write, an upgrade that keeps every row, a second migrate and a failed one that change
nothing, and a restore that puts a backup back after backing the current database up. The tests that migrate give the
code a step of their own, from one version below the code's, so they hold whatever steps the code has; three tests run
the code's own steps, from version 9, from version 13 and from version 14. Only a superuser may create pgvector's extension, so the
tests of a database without it run as the session's superuser (TestDatabase.superuser).
"""

import hashlib
import io
import re
from datetime import datetime, timedelta, tzinfo
from pathlib import Path

import pytest
from rich.console import Console
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlmodel import SQLModel
from support.databases import ENVIRONMENT, TestDatabase, as_superuser, database_snapshot, execute, open_database, raw_engine
from support.fakes import FakeTextEmbedder
from support.harness import MARKET_OPEN
from test_stock_page import article
from trading_stack import MovableClock

import c_infrastructure.database.db_connector as db_connector
import c_infrastructure.database.models.schema_version_dto as schema_version
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.order import Order
from a_domain.types.enums import ExecutionProvider, InformationSource, OrderType, TimeInForce, TradeAction, Workflow
from a_domain.types.ids import new_decision_id
from c_infrastructure.database.db_connector import DatabaseCommandError, DatabaseConnector, OutdatedDatabaseError
from c_infrastructure.database.models.schema_version_dto import FIRST_SCHEMA_VERSION, SCHEMA_VERSION
from c_infrastructure.database.models.user_dto import LEGACY_OWNER_ID
from c_infrastructure.database.repositories.article_index import SqlArticleIndex
from c_infrastructure.database.repositories.trading_journal import TradingJournal
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


async def test_the_steps_from_version_9_give_a_run_its_ranking_follow_columns_and_the_follow_its_schedule_and_keep_every_run(
    tmp_path: Path, output: io.StringIO
) -> None:
    connector = await current_database(tmp_path)
    await execute(
        "ALTER TABLE workflow_runs DROP COLUMN ranking_formula, DROP COLUMN ranking_decided_on, DROP COLUMN scheduled, "
        "DROP COLUMN ranking_open",
        "ALTER TABLE users DROP COLUMN ranking_follow_time, DROP COLUMN ranking_follow_broker",
        "INSERT INTO users (user_id, username_sealed, username_index, email_sealed, email_index, password_hash, role, status, "
        "created_at, updated_at) VALUES ('u-before', '\\x01', '\\x02', '\\x03', '\\x04', 'none', 'USER', 'ACTIVE', "
        "'2026-11-03 06:00:00', '2026-11-03 06:00:00')",
        "INSERT INTO workflow_runs (run_id, workflow, execution_provider, start_time, total_scanned, buzz_scanned, buzz_qualified, "
        "sentiment_analysed, passed_technical, ai_analysed, signals_generated, orders_submitted, orders_filled, orders_refused, "
        "stale_market_data_count, errors, execution_log, owner_id) VALUES ('00000000-0000-4000-8000-000000000001', 'RANKING_FOLLOW', "
        "'MOCK', '2026-11-03 06:00:00', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, '[]', '[]', 'local')",
        "UPDATE schema_version SET version = 9",
    )

    try:
        with pytest.raises(OutdatedDatabaseError, match="just db-migrate"):
            await connector.init_db()

        assert await commands.migrate(connector) == 0
        await connector.init_db()
    finally:
        await connector.close()

    after = await database_snapshot()
    assert "9 -> 10 add_the_ranking_formula_of_a_run" in output.getvalue()
    assert "10 -> 11 add_the_schedule_of_the_ranking_follow" in output.getvalue()
    assert "11 -> 12 add_what_a_ranking_follow_left_open" in output.getvalue()
    assert "12 -> 13 add_the_account_of_the_scheduled_follow" in output.getvalue()
    assert "13 -> 14 add_the_vector_extension" in output.getvalue()
    assert "14 -> 15 add_the_unconfirmed_order_status" in output.getvalue()
    assert after["schema_version"][1] == [("15",)]
    assert {"ranking_formula", "ranking_decided_on", "scheduled", "ranking_open"} <= set(after["workflow_runs"][0])
    assert "ranking_follow_time" in after["users"][0]
    followed_on = {row[after["users"][0].index("ranking_follow_broker")] for row in after["users"][1]}
    assert after["users"][1] and followed_on == {"MOCK"}
    [run] = after["workflow_runs"][1]
    assert run[after["workflow_runs"][0].index("scheduled")] == "False"
    assert run[after["workflow_runs"][0].index("ranking_open")] == "None"


AT_VERSION_14 = (
    "ALTER TYPE orderstatus RENAME TO orderstatus_of_version_15",
    "CREATE TYPE orderstatus AS ENUM ('PENDING', 'SUBMITTED', 'FILLED', 'CANCELLED', 'FAILED', 'REJECTED')",
    "ALTER TABLE orders ALTER COLUMN status TYPE orderstatus USING status::text::orderstatus",
    "DROP TYPE orderstatus_of_version_15",
    "UPDATE schema_version SET version = 14",
)
"""A database of version 14, whose orders' status type has no UNCONFIRMED."""


async def order_statuses() -> list[str]:
    """The values the orders' status type takes, in its own order."""
    engine = raw_engine()

    async with engine.connect() as connection:
        labels = await connection.execute(
            text("SELECT enumlabel FROM pg_enum WHERE enumtypid = 'orderstatus'::regtype ORDER BY enumsortorder")
        )
        statuses = list(labels.scalars())

    await engine.dispose()
    return statuses


async def test_the_step_from_version_14_lets_an_order_await_settlement_and_keeps_every_row(
    tmp_path: Path, output: io.StringIO
) -> None:
    connector = await current_database(tmp_path)
    await execute(*AT_VERSION_14)
    before = await database_snapshot()

    try:
        with pytest.raises(OutdatedDatabaseError, match="just db-migrate"):
            await connector.init_db()

        assert await commands.migrate(connector) == 0
        await connector.init_db()
        after = await database_snapshot()
        journal = TradingJournal(connector.for_owner(LEGACY_OWNER_ID))
        run = SystemStats(workflow=Workflow.MANUAL_BUY, execution_provider=ExecutionProvider.SHIOAJI, start_time=MARKET_OPEN)
        run.end_time = MARKET_OPEN
        order = Order(
            run_id=run.run_id,
            decision_id=new_decision_id(),
            stock_id="2330",
            action=TradeAction.BUY,
            order_type=OrderType.LIMIT,
            quantity=1000,
            limit_price=100.0,
            time_in_force=TimeInForce.IOC,
            created_at=MARKET_OPEN,
            updated_at=MARKET_OPEN,
        )
        order.leave_unconfirmed("the broker's answer was lost", now=MARKET_OPEN)
        await journal.save_run(run)
        await journal.save_order(order)
        unsettled = await journal.unsettled_orders(ExecutionProvider.SHIOAJI)
    finally:
        await connector.close()

    assert "14 -> 15 add_the_unconfirmed_order_status" in output.getvalue()
    assert after["schema_version"][1] == [(str(SCHEMA_VERSION),)]
    assert {table: after[table] for table in before.keys() - {"schema_version"}} == {
        table: rows for table, rows in before.items() if table != "schema_version"
    }
    assert await order_statuses() == ["PENDING", "SUBMITTED", "UNCONFIRMED", "FILLED", "CANCELLED", "FAILED", "REJECTED"]
    assert unsettled == [order]


REVENUE = "十月營收創新高 年增四成"
"""The title of the one article the tests of the vector extension index and search."""


async def index_and_search(connector: DatabaseConnector) -> tuple[int, bool]:
    """How many vectors a sync of one article wrote into the connector's database, and whether a search of its title finds it."""
    revenue = article(REVENUE, InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(days=1), "https://news.example/r")
    index = SqlArticleIndex(connector, "fake-model", FakeTextEmbedder(), MovableClock(MARKET_OPEN), 300)
    embedded = await index.sync("2330", [revenue])
    return embedded, await index.search("2330", REVENUE, None, None, 5) == [revenue.key]


async def vector_storage() -> str:
    """How article_vectors stores its vectors: "p" (PLAIN) keeps each in its row."""
    engine = raw_engine()

    async with engine.connect() as connection:
        storage = await connection.scalar(
            text("SELECT attstorage::text FROM pg_attribute WHERE attrelid = 'article_vectors'::regclass AND attname = 'vector'")
        )

    await engine.dispose()
    return str(storage)


async def test_the_step_from_version_13_gives_a_database_the_vector_extension_and_keeps_every_row(
    tmp_path: Path, output: io.StringIO, monkeypatch: pytest.MonkeyPatch, test_database: TestDatabase
) -> None:
    monkeypatch.setenv("DB_USER", test_database.superuser)
    connector = open_database(tmp_path)
    await connector.init_db()
    at_version_13 = "DROP TABLE article_vectors, chat_conversations; DROP EXTENSION vector; UPDATE schema_version SET version = 13"
    await as_superuser(test_database.superuser, test_database.name, "; ".join((*ROWS, at_version_13)))

    try:
        with pytest.raises(OutdatedDatabaseError, match="just db-migrate"):
            await connector.init_db()

        assert await commands.migrate(connector) == 0
        await connector.init_db()
        indexed = await index_and_search(connector)
        state = await connector.state()
    finally:
        await connector.close()

    assert "13 -> 14 add_the_vector_extension" in output.getvalue()
    assert (state.stamps, indexed) == ((SCHEMA_VERSION,), (1, True))
    assert {name: rows for name, rows in state.rows.items() if rows} == {**HELD, "article_vectors": 1}
    assert await vector_storage() == "p"


async def test_a_new_database_gets_the_vector_extension_at_its_first_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, test_database: TestDatabase
) -> None:
    monkeypatch.setenv("DB_USER", test_database.superuser)
    await execute("DROP SCHEMA public CASCADE", "CREATE SCHEMA public")
    connector = open_database(tmp_path)

    try:
        await connector.init_db()
        indexed = await index_and_search(connector)
    finally:
        await connector.close()

    assert indexed == (1, True)


async def test_a_new_database_that_cannot_get_the_vector_extension_is_refused_with_the_remedy(tmp_path: Path) -> None:
    # Without a schema to create it in, CREATE EXTENSION fails for any role, a superuser's included.
    await execute("DROP SCHEMA public CASCADE")
    connector = open_database(tmp_path)

    try:
        with pytest.raises(OutdatedDatabaseError) as refused:
            await connector.init_db()
    finally:
        await connector.close()
        await execute("CREATE SCHEMA public")

    assert str(refused.value).startswith("The database could not create pgvector's extension")
    assert 'as a superuser: psql -d <DB_NAME> -c "CREATE EXTENSION vector"' in str(refused.value)


async def test_a_restore_into_a_new_database_gives_it_the_vector_extension_and_the_vectors_back(
    tmp_path: Path, output: io.StringIO, monkeypatch: pytest.MonkeyPatch, test_database: TestDatabase
) -> None:
    monkeypatch.setenv("DB_USER", test_database.superuser)
    connector = open_database(tmp_path)

    try:
        await connector.init_db()
        await index_and_search(connector)
        await commands.backup(connector)
        [backup] = backups(tmp_path)
        await execute("DROP SCHEMA public CASCADE", "CREATE SCHEMA public")
        await commands.restore(connector, backup, confirmed=True)
        state = await connector.state()
    finally:
        await connector.close()

    assert f"The database had no table, so no backup was made, then restored {backup}:" in output.getvalue()
    assert (state.stamps, state.rows["article_vectors"]) == ((SCHEMA_VERSION,), 1)


async def test_a_restore_into_a_database_that_cannot_get_the_vector_extension_names_the_remedy_and_restores_nothing(
    tmp_path: Path, output: io.StringIO
) -> None:
    connector = await current_database(tmp_path)

    try:
        await commands.backup(connector)
        [backup] = backups(tmp_path)
        # Without a schema to create it in, CREATE EXTENSION fails for any role, a superuser's included.
        await execute("DROP SCHEMA public CASCADE")

        with pytest.raises(DatabaseCommandError) as refused:
            await commands.restore(connector, backup, confirmed=True)
    finally:
        await connector.close()
        await execute("CREATE SCHEMA public")

    assert str(refused.value).startswith("The database could not create pgvector's extension")
    assert str(refused.value).endswith('"CREATE EXTENSION vector"\nNothing was restored.')
    assert await database_snapshot() == {}


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


async def test_restore_into_a_database_without_a_table_makes_no_backup(
    tmp_path: Path, output: io.StringIO, test_database: TestDatabase
) -> None:
    connector = await current_database(tmp_path)

    try:
        await commands.backup(connector)
        [backup] = backups(tmp_path)
        await connector.close()
        await execute("DROP SCHEMA public CASCADE", "CREATE SCHEMA public")
        await as_superuser(test_database.superuser, test_database.name, "CREATE EXTENSION vector")
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
