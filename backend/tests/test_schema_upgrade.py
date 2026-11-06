"""
The upgrades on a real database of each backend. From schema version 2 (one owner, no owner columns) to 3 (rows have
owners): every row is kept and becomes the legacy owner's, which is what the first administrator takes at setup; a
second start changes nothing; and a failure inside the step leaves the database exactly as version 2 left it. From 3
to 4 (a user's AI model): every user keeps their row and signs in as before on the site's default model.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import Connection, inspect, text
from support.databases import BACKENDS, create_version_2_tables, create_version_3_tables, database_config, empty_database, raw_engine
from support.harness import MARKET_OPEN
from trading_stack import MovableClock, SilentLogger

import c_infrastructure.database.models.schema_version_dto as schema_version
from a_domain.types.enums import AiProvider, DatabaseBackend, Role
from a_domain.types.ids import RunId, UserId
from c_infrastructure.database.db_connector import DatabaseCommandError, DatabaseConnector
from c_infrastructure.database.models.schema_version_dto import SCHEMA_VERSION
from c_infrastructure.database.models.user_dto import LEGACY_OWNER_ID, UserKeys
from c_infrastructure.database.repositories.trading_journal import TradingJournal
from c_infrastructure.database.repositories.user_store import SqlUserStore
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from c_infrastructure.trading.mock.mock_execution_provider import MockExecutionProvider

pytestmark = pytest.mark.asyncio

RUN, DECISION, ORDER, SNAPSHOT = (UUID(int=number) for number in (1, 2, 3, 4))
AT = datetime(2026, 11, 3, 6, 0)
JOURNAL_TABLES = ("workflow_runs", "trade_signals", "orders", "account_snapshots", "run_stock_reports")

# fmt: off
LEGACY_ROWS: list[tuple[str, dict[str, Any]]] = [
    (
        "workflow_runs",
        {
            "run_id": RUN, "workflow": "FULL_CYCLE", "execution_provider": "MOCK", "order_mode": "MOCK_ONLY",
            "start_time": AT, "end_time": AT, "technical_strategy_id": "balanced", "ai_model": None,
            "total_scanned": 3, "buzz_scanned": 0, "buzz_qualified": 0, "sentiment_analysed": 0, "passed_technical": 1,
            "ai_analysed": 1, "signals_generated": 1, "orders_submitted": 1, "orders_filled": 1, "orders_refused": 0,
            "stale_market_data_count": 0, "errors": "[]", "execution_log": "[]", "failure": None,
        },
    ),
    (
        "trade_signals",
        {
            "decision_id": DECISION, "run_id": RUN, "stock_id": "2330", "action": "BUY", "source": "COMBINED",
            "score": 80, "reason": "strong", "quantity": 1000, "stop_loss_price": 90.0, "generated_at": AT,
            "price_at_signal": 100.0, "price_observed_at": AT, "history_until": None, "technical_report": None,
            "ai_report": None,
        },
    ),
    (
        "orders",
        {
            "id": ORDER, "run_id": RUN, "decision_id": DECISION, "stock_id": "2330", "action": "BUY",
            "order_type": "LIMIT", "quantity": 1000, "limit_price": 100.0, "time_in_force": "IOC", "status": "FILLED",
            "reason": None, "filled_quantity": 1000, "average_filled_price": 100.0, "fee": 142, "tax": 0,
            "realized_pnl": None, "created_at": AT, "updated_at": AT,
        },
    ),
    (
        "account_snapshots",
        {
            "snapshot_id": SNAPSHOT, "taken_at": AT, "run_id": RUN, "order_id": ORDER, "cash": 899858.0,
            "positions": json.dumps([{"stock_id": "2330", "quantity": 1000, "average_cost": 100.142, "mark_price": 100.0,
                                      "marked_at": None, "unrealized_pnl": 0.0}]),
        },
    ),
    ("run_stock_reports", {"run_id": RUN, "position": 0, "stock_id": "2330", "report": json.dumps({"stock_id": "2330"})}),
    ("watchlists", {"stock_id": "2330", "type": "technical", "created_at": AT, "expires_at": None}),
    ("watchlists", {"stock_id": "2330", "type": "manual", "created_at": AT, "expires_at": None}),
    ("watchlists", {"stock_id": "2603", "type": "buzz", "created_at": AT, "expires_at": None}),
    ("mock_cash", {"account_id": "my-book", "current_cash": 899858.0, "initial_cash": 1000000.0, "created_at": AT, "updated_at": AT}),
    (
        "mock_positions",
        {"account_id": "my-book", "stock_id": "2330", "quantity": 1000, "average_cost": 100.142, "opened_at": AT, "updated_at": AT},
    ),
]
"""The single owner's data, the mock book and the technical settings each under a changed id, as a customized version 2 kept them."""
# fmt: on


TECHNICAL_SETTINGS = (
    "INSERT INTO technical_settings (owner_id, active_strategy_id, buzz_strategy_id, revision) VALUES ('shiou', 'trend', 'buzz', 4)",
    "INSERT INTO technical_strategies (owner_id, strategy_id, position, name, base_score, block_failure_penalty, "
    "failure_score_reduction, pass_score_increase) VALUES ('shiou', 'trend', 0, 'Trend', 50, 30, 10, 10)",
)
"""The technical settings under technical.owner_id changed to 'shiou', with one strategy."""


def stored(backend: DatabaseBackend, value: Any) -> Any:
    """A value as version 2 bound it: SQLite kept UUIDs as 32 hex digits and datetimes as text."""
    if backend == DatabaseBackend.SQLITE and isinstance(value, UUID):
        return value.hex

    if backend == DatabaseBackend.SQLITE and isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="microseconds")

    return value


async def version_2_database(backend: DatabaseBackend, folder: Path, extra_rows: tuple[str, ...] = ()) -> DatabaseConnector:
    """
    A database as version 2 left it: its tables, the stamp 2, and the single owner's runs, watchlist, mock book and
    technical settings, then `extra_rows`, each an INSERT statement.
    """
    connector = await empty_database(backend, folder)
    await create_version_2_tables(backend, folder)
    engine = raw_engine(backend, folder)

    async with engine.begin() as connection:
        for table, row in LEGACY_ROWS:
            columns = ", ".join(row)
            await connection.execute(
                text(f"INSERT INTO {table} ({columns}) VALUES ({', '.join(f':{column}' for column in row)})"),
                {column: stored(backend, value) for column, value in row.items()},
            )

        for statement in (*TECHNICAL_SETTINGS, *extra_rows):
            await connection.execute(text(statement))

    await engine.dispose()
    return connector


def snapshot_of(connection: Connection) -> dict[str, Any]:
    """Every table's columns and rows, and the stamp: what an upgrade that rolled back must leave as it was."""
    tables = inspect(connection)
    dump: dict[str, Any] = {}

    for table in sorted(tables.get_table_names()):
        columns = sorted(column["name"] for column in tables.get_columns(table))
        rows = sorted(
            tuple(str(value) for value in row) for row in connection.execute(text(f"SELECT {', '.join(columns)} FROM {table}"))
        )
        dump[table] = (columns, rows)

    return dump


async def database_snapshot(backend: DatabaseBackend, folder: Path) -> dict[str, Any]:
    engine = raw_engine(backend, folder)

    async with engine.connect() as connection:
        dump = await connection.run_sync(snapshot_of)

    await engine.dispose()
    return dump


@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_version_2_database_keeps_every_row_and_gives_it_to_the_legacy_owner(backend: DatabaseBackend, tmp_path: Path) -> None:
    connector = await version_2_database(backend, tmp_path)
    before = await database_snapshot(backend, tmp_path)

    try:
        await connector.migrate()
        after = await database_snapshot(backend, tmp_path)
        journal = TradingJournal(connector.for_owner(LEGACY_OWNER_ID))
        run = await journal.find_run(RunId(RUN))
        [snapshot] = await journal.snapshots()
        watched = await WatchlistRepository(
            connector.for_owner(LEGACY_OWNER_ID), SilentLogger(), MovableClock(MARKET_OPEN)
        ).get_active()
        account = await MockExecutionProvider(
            connector.for_owner(LEGACY_OWNER_ID), database_config(backend, tmp_path), SilentLogger()
        ).get_account()
        strangers_run = await TradingJournal(connector.for_owner(UserId("someone-else"))).find_run(RunId(RUN))
    finally:
        await connector.close()

    assert after["schema_version"][1] == [(str(SCHEMA_VERSION),)]
    assert {table: len(rows) for table, (_, rows) in after.items() if table in before} == {
        table: len(rows) for table, (_, rows) in before.items()
    }
    for table in (*JOURNAL_TABLES, "watchlists", "mock_cash", "mock_positions", "technical_settings", "technical_strategies"):
        owners = {row[after[table][0].index("owner_id")] for row in after[table][1]}
        assert owners == {LEGACY_OWNER_ID}, table

    assert run is not None and run.orders_filled == 1 and strangers_run is None
    assert (snapshot.account.account_id, snapshot.account.cash) == (LEGACY_OWNER_ID, 899858.0)
    assert sorted((entry.stock_id, entry.watchlist_type.value) for entry in watched) == [
        ("2330", "manual"),
        ("2330", "technical"),
        ("2603", "buzz"),
    ]
    assert (account.cash, [(position.stock_id, position.quantity) for position in account.positions]) == (899858.0, [("2330", 1000)])
    assert after["technical_settings"][1] == [("trend", "buzz", "local", "4")]
    assert [row[after["technical_strategies"][0].index("name")] for row in after["technical_strategies"][1]] == ["Trend"]


@pytest.mark.parametrize(
    ("extra_row", "named"),
    [
        (
            "INSERT INTO mock_cash (account_id, current_cash, initial_cash, created_at, updated_at) "
            "VALUES ('mock-dev', 5.0, 5.0, '2026-11-03 06:00:00', '2026-11-03 06:00:00')",
            "mock book under 2 ids: mock-dev, my-book",
        ),
        (
            "INSERT INTO technical_settings (owner_id, active_strategy_id, buzz_strategy_id, revision) "
            "VALUES ('local', 'trend', 'buzz', 0)",
            "technical settings under 2 ids: local, shiou",
        ),
    ],
)
@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_version_2_database_with_data_under_two_ids_is_refused_unchanged(
    backend: DatabaseBackend, tmp_path: Path, extra_row: str, named: str
) -> None:
    connector = await version_2_database(backend, tmp_path, (extra_row,))
    before = await database_snapshot(backend, tmp_path)

    try:
        with pytest.raises(DatabaseCommandError, match=named):
            await connector.migrate()
    finally:
        await connector.close()

    assert await database_snapshot(backend, tmp_path) == before


@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_second_start_after_the_upgrade_changes_nothing(backend: DatabaseBackend, tmp_path: Path) -> None:
    connector = await version_2_database(backend, tmp_path)
    await connector.migrate()
    await connector.init_db()
    upgraded = await database_snapshot(backend, tmp_path)

    try:
        await connector.init_db()
    finally:
        await connector.close()

    assert await database_snapshot(backend, tmp_path) == upgraded


@pytest.mark.parametrize("backend", BACKENDS)
async def test_an_upgraded_database_has_the_columns_of_a_new_one(backend: DatabaseBackend, tmp_path: Path) -> None:
    (tmp_path / "upgraded").mkdir()
    (tmp_path / "new").mkdir()
    upgraded = await version_2_database(backend, tmp_path / "upgraded")
    await upgraded.migrate()
    await upgraded.init_db()
    await upgraded.close()
    layout = {table: columns for table, (columns, _) in (await database_snapshot(backend, tmp_path / "upgraded")).items()}

    new = await empty_database(backend, tmp_path / "new")
    await new.init_db()
    await new.close()

    assert layout == {table: columns for table, (columns, _) in (await database_snapshot(backend, tmp_path / "new")).items()}


class FailsAfterFirstStatement:
    """
    The upgrade's connection, which raises right after the step's first statement that changes something ran, as a crash
    would stop it. The step's reads before it do not count.
    """

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.dialect = connection.dialect
        self.statements = 0

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if self.statements == 1:
            raise RuntimeError("the upgrade stopped after its first statement")

        self.statements += not str(statement).lstrip().upper().startswith(("SELECT", "UNION"))
        return await self.connection.execute(statement, *args, **kwargs)

    async def run_sync(self, *args: Any, **kwargs: Any) -> Any:
        return await self.connection.run_sync(*args, **kwargs)


@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_failure_inside_the_owner_step_leaves_the_version_2_database_as_it_was(
    backend: DatabaseBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = await version_2_database(backend, tmp_path)
    before = await database_snapshot(backend, tmp_path)
    owner_step = schema_version.give_rows_their_owner

    async def failing_owner_step(connection: Any) -> None:
        await owner_step(FailsAfterFirstStatement(connection))

    monkeypatch.setattr(schema_version, "UPGRADES", (schema_version.record_run_failures, failing_owner_step))

    try:
        with pytest.raises(RuntimeError, match="after its first statement"):
            await connector.migrate()
    finally:
        await connector.close()

    after = await database_snapshot(backend, tmp_path)
    assert after == before
    assert after["schema_version"][1] == [("2",)]


ACCOUNTS_KEY = SecretStr("A" * 43)
"""32 zero-ish bytes in base64url: the key the version-3 users below were sealed with."""


async def version_3_database(backend: DatabaseBackend, folder: Path) -> DatabaseConnector:
    """A database as version 3 left it: its tables, the stamp 3, the administrator and a user, and the administrator's run."""
    connector = await empty_database(backend, folder)
    await create_version_3_tables(backend, folder)
    keys, engine = UserKeys(ACCOUNTS_KEY), raw_engine(backend, folder)
    users = [(LEGACY_OWNER_ID, "owner", "ADMINISTRATOR"), ("u-member", "member", "USER")]
    run = {"owner_id": LEGACY_OWNER_ID, **dict(LEGACY_ROWS)["workflow_runs"]}

    async with engine.begin() as connection:
        for user_id, name, role in users:
            await connection.execute(
                text(
                    "INSERT INTO users (user_id, username_sealed, username_index, email_sealed, email_index, password_hash, "
                    "role, status, created_at, updated_at) VALUES (:user_id, :username_sealed, :username_index, "
                    ":email_sealed, :email_index, 'not a hash', :role, 'ACTIVE', :at, :at)"
                ),
                {
                    "user_id": user_id,
                    "username_sealed": keys.seal("username", user_id, name),
                    "username_index": keys.username_index(name),
                    "email_sealed": keys.seal("email", user_id, f"{name}@example.com"),
                    "email_index": keys.email_index(f"{name}@example.com"),
                    "role": role,
                    "at": stored(backend, AT),
                },
            )

        await connection.execute(
            text(f"INSERT INTO workflow_runs ({', '.join(run)}) VALUES ({', '.join(f':{column}' for column in run)})"),
            {column: stored(backend, value) for column, value in run.items()},
        )

    await engine.dispose()
    return connector


@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_version_3_database_gains_the_ai_model_and_keeps_every_user_on_the_site_default(
    backend: DatabaseBackend, tmp_path: Path
) -> None:
    connector = await version_3_database(backend, tmp_path)
    before = await database_snapshot(backend, tmp_path)

    try:
        migration = await connector.migrate()
        await connector.init_db()
        store = SqlUserStore(connector, ACCOUNTS_KEY, SilentLogger())
        upgraded = await store.users()
        await store.save_ai_model(UserId("u-member"), AiProvider.OPENAI, AT.replace(tzinfo=UTC))
        chosen = await store.find(UserId("u-member"))
        run = await TradingJournal(connector.for_owner(LEGACY_OWNER_ID)).find_run(RunId(RUN))
    finally:
        await connector.close()

    after = await database_snapshot(backend, tmp_path)
    assert list(migration.before.pending) == ["3 -> 4 add_user_ai_model"]
    assert after["schema_version"][1] == [(str(SCHEMA_VERSION),)]
    assert {table: len(rows) for table, (_, rows) in after.items() if table in before} == {
        table: len(rows) for table, (_, rows) in before.items()
    }
    assert set(after["users"][0]) - set(before["users"][0]) == {"ai_model"}
    assert [(user.username, user.role, user.ai_model) for user in upgraded] == [
        ("owner", Role.ADMINISTRATOR, None),
        ("member", Role.USER, None),
    ]
    assert chosen is not None and chosen.ai_model == AiProvider.OPENAI
    assert run is not None and run.orders_filled == 1


@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_failure_after_the_ai_model_step_leaves_the_version_3_database_as_it_was(
    backend: DatabaseBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = await version_3_database(backend, tmp_path)
    before = await database_snapshot(backend, tmp_path)

    async def fails_after_the_column(connection: Any) -> None:
        await schema_version.add_user_ai_model(connection)
        raise RuntimeError("the upgrade stopped after adding the column")

    monkeypatch.setattr(schema_version, "UPGRADES", (*schema_version.UPGRADES[:2], fails_after_the_column))

    try:
        with pytest.raises(DatabaseCommandError, match="after adding the column"):
            await connector.migrate()
    finally:
        await connector.close()

    after = await database_snapshot(backend, tmp_path)
    assert after == before
    assert after["schema_version"][1] == [("3",)]
