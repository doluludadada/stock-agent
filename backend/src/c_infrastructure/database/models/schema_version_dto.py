from collections.abc import Awaitable, Callable, Sequence
from typing import ClassVar

from sqlalchemy import JSON, Connection, column, inspect, select, table, text, update
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlmodel import Field, SQLModel

from c_infrastructure.database.models.user_dto import LEGACY_OWNER_ID


class OutdatedDatabaseError(RuntimeError):
    """
    The database is of an older schema version, which `just db-migrate` upgrades, or it holds tables of a schema version
    no upgrade reaches, or of none, or a table with columns other than its SQLModel class declares, or data an upgrade
    step cannot carry over without guessing. create_all never alters an existing table. Startup raises it, and so do
    `just db-migrate` and its steps; the CLI, the Web API and the database commands catch it to print the remedy, so it
    belongs to the database adapter rather than to the domain's errors.
    """


class SchemaVersionDTO(SQLModel, table=True):
    """The one row startup writes when it creates the tables, the SCHEMA_VERSION it created them with; an upgrade raises it."""

    __tablename__: ClassVar[str] = "schema_version"

    version: int = Field(primary_key=True)


async def record_run_failures(connection: AsyncConnection) -> None:
    """
    Version 1 to 2: workflow_runs gains `failure`. A version 1 run kept the exception that stopped it only as the error
    RunHistory wrote, "Run aborted: <type>: <message>", which no other error ever started with, so it is copied from there.
    """
    marker = "Run aborted: "
    runs = table("workflow_runs", column("run_id"), column("errors", JSON), column("failure"))
    await connection.execute(text("ALTER TABLE workflow_runs ADD COLUMN failure VARCHAR"))

    for run_id, errors in (await connection.execute(select(runs.c.run_id, runs.c.errors))).all():
        if aborted := [error.removeprefix(marker) for error in errors if error.startswith(marker)]:
            await connection.execute(update(runs).where(runs.c.run_id == run_id).values(failure=aborted[-1]))


OWNER_COLUMN_TABLES = ("workflow_runs", "trade_signals", "orders", "account_snapshots", "run_stock_reports")
"""The version-2 tables of the trading journal, which held the single owner's rows with no owner column."""

OWNER_INDEXES = (
    "CREATE INDEX ix_workflow_runs_owner_start ON workflow_runs (owner_id, start_time)",
    "CREATE INDEX ix_account_snapshots_owner_taken ON account_snapshots (owner_id, taken_at)",
)

MOCK_BOOK = (
    "ALTER TABLE mock_cash RENAME COLUMN account_id TO owner_id",
    "ALTER TABLE mock_positions RENAME COLUMN account_id TO owner_id",
    "UPDATE mock_cash SET owner_id = :owner",
    "UPDATE mock_positions SET owner_id = :owner",
)
"""
Version 2's mock account was mock_trading.account_id, mock-dev as shipped. Its column becomes owner_id, which makes the
mock book an owned table, and the book becomes the legacy owner's whatever account id it had.
"""

OWNER_STEP = {
    "sqlite": (
        *(f"ALTER TABLE {name} ADD COLUMN owner_id VARCHAR NOT NULL DEFAULT '{LEGACY_OWNER_ID}'" for name in OWNER_COLUMN_TABLES),
        *OWNER_INDEXES,
        # SQLite cannot change a primary key in place. The copy goes in first, so a failure before the drop loses nothing.
        "CREATE TABLE watchlists_v3 (owner_id VARCHAR NOT NULL, stock_id VARCHAR NOT NULL, type VARCHAR NOT NULL, "
        "created_at DATETIME NOT NULL, expires_at DATETIME, PRIMARY KEY (owner_id, stock_id, type))",
        f"INSERT INTO watchlists_v3 (owner_id, stock_id, type, created_at, expires_at) "
        f"SELECT '{LEGACY_OWNER_ID}', stock_id, type, created_at, expires_at FROM watchlists",
        "DROP TABLE watchlists",
        "ALTER TABLE watchlists_v3 RENAME TO watchlists",
        "CREATE INDEX ix_watchlists_expires_at ON watchlists (expires_at)",
        *MOCK_BOOK,
    ),
    "postgresql": (
        *(
            statement
            for name in (*OWNER_COLUMN_TABLES, "watchlists")
            for statement in (
                f"ALTER TABLE {name} ADD COLUMN owner_id VARCHAR NOT NULL DEFAULT '{LEGACY_OWNER_ID}'",
                f"ALTER TABLE {name} ALTER COLUMN owner_id DROP DEFAULT",
            )
        ),
        *OWNER_INDEXES,
        "ALTER TABLE watchlists DROP CONSTRAINT watchlists_pkey",
        "ALTER TABLE watchlists ADD PRIMARY KEY (owner_id, stock_id, type)",
        *MOCK_BOOK,
    ),
}
"""
Version 2 to 3, per database backend. SQLite keeps the column default, which it cannot drop; every insert names the
owner anyway, and the owner guard refuses a row of another owner.
"""

SINGLE_OWNER_TABLES = {
    "mock book": ("SELECT account_id FROM mock_cash UNION SELECT account_id FROM mock_positions", ("mock_cash", "mock_positions")),
    "technical settings": ("SELECT owner_id FROM technical_settings", ("technical_settings",)),
}
"""The version-2 data kept under an id, each with the query of its ids and the tables to delete another id's rows from."""

TECHNICAL_TABLES = ("technical_settings", "technical_strategies", "technical_indicators", "technical_rules", "technical_formula_nodes")
"""The technical settings' tables, each after the tables its foreign keys name."""


async def one_owner_or_refuse(connection: AsyncConnection) -> None:
    """
    A version-2 database belonged to one owner, but a changed mock_trading.account_id or technical.owner_id left rows of
    a second id beside the first. Version 3 cannot tell whose they are, so it refuses, naming them, instead of merging
    them into one owner's.
    """
    for data, (query, tables) in SINGLE_OWNER_TABLES.items():
        ids = sorted(found for (found,) in (await connection.execute(text(query))).all())

        if len(ids) > 1:
            raise OutdatedDatabaseError(
                f"Version 3 gives the single owner's data to its first administrator, but this database keeps the {data} "
                f"under {len(ids)} ids: {', '.join(ids)}. Keep one: delete the rows of the others from "
                f"{' and '.join(tables)}, then run `just db-migrate` again. Nothing was changed."
            )


async def move_technical_settings(connection: AsyncConnection) -> None:
    """
    The technical settings kept under another id than the legacy owner's (a changed technical.owner_id) become the
    legacy owner's: copied under the new id parents first, then deleted under the old one children first, since no
    foreign key updates its children.
    """
    owners = [found for (found,) in (await connection.execute(text("SELECT owner_id FROM technical_settings"))).all()]

    if owners in ([], [LEGACY_OWNER_ID]):
        return

    def columns_of(sync_connection: Connection) -> dict[str, list[str]]:
        tables = inspect(sync_connection)
        return {
            name: [found["name"] for found in tables.get_columns(name) if found["name"] != "owner_id"] for name in TECHNICAL_TABLES
        }

    columns, moved = await connection.run_sync(columns_of), {"owner": LEGACY_OWNER_ID, "old": owners[0]}

    for name in TECHNICAL_TABLES:
        kept = ", ".join(columns[name])
        await connection.execute(
            text(f"INSERT INTO {name} (owner_id, {kept}) SELECT :owner, {kept} FROM {name} WHERE owner_id = :old"), moved
        )

    for name in reversed(TECHNICAL_TABLES):
        await connection.execute(text(f"DELETE FROM {name} WHERE owner_id = :old"), moved)


async def give_rows_their_owner(connection: AsyncConnection) -> None:
    """
    Version 2 to 3: every journal, watchlist, mock-book and technical-settings row becomes the legacy owner's, whatever
    id it was kept under, and the watchlist's key starts with the owner, so two users may watch one stock. Chroma's
    decision memory keeps the legacy owner's collection name, so it does not change. No row is deleted, but for a
    moved technical-settings row's old copy.
    """
    await one_owner_or_refuse(connection)

    for statement in OWNER_STEP[connection.dialect.name]:
        await connection.execute(text(statement), {"owner": LEGACY_OWNER_ID} if ":owner" in statement else {})

    await move_technical_settings(connection)


AI_MODEL_STEP = {
    "sqlite": ("ALTER TABLE users ADD COLUMN ai_model VARCHAR(6)",),
    "postgresql": (
        "CREATE TYPE aiprovider AS ENUM ('OPENAI', 'GROK', 'GEMINI', 'GROQ', 'NVIDIA', 'CLAUDE')",
        "ALTER TABLE users ADD COLUMN ai_model aiprovider",
    ),
}
"""
Version 3 to 4, per database backend: users.ai_model stores an AiProvider member's name, as SQLModel stores every enum,
in a VARCHAR as long as the longest name on SQLite and in the named ENUM type aiprovider on PostgreSQL. Version 3 had
no column of that type, so the type is new too.
"""


async def add_user_ai_model(connection: AsyncConnection) -> None:
    """
    Version 3 to 4: users gains ai_model, the AI model a user chose. Every existing user gets NULL, the site's default.
    A database upgraded from version 2 has no users table until its next start, whose create_all makes it with the
    column, so there the step changes nothing.
    """
    tables = await connection.run_sync(lambda sync_connection: inspect(sync_connection).get_table_names())

    if "users" not in tables:
        return

    for statement in AI_MODEL_STEP[connection.dialect.name]:
        await connection.execute(text(statement))


FOLLOW_STEP = {
    "sqlite": (
        "ALTER TABLE workflow_runs ADD COLUMN followed_run_id CHAR(32)",
        "ALTER TABLE trade_signals ADD COLUMN followed_decision_id CHAR(32)",
    ),
    "postgresql": (
        "ALTER TYPE workflow ADD VALUE 'FOLLOW' AFTER 'MANUAL_BUY'",
        "ALTER TYPE signalsource ADD VALUE 'FOLLOW'",
        "ALTER TABLE workflow_runs ADD COLUMN followed_run_id UUID",
        "ALTER TABLE trade_signals ADD COLUMN followed_decision_id UUID",
    ),
}
"""
Version 4 to 5's first part, per database backend: workflow_runs.followed_run_id and trade_signals.followed_decision_id, stored as
SQLModel stores a UUID (CHAR(32) on SQLite, UUID on PostgreSQL), and the member FOLLOW of the enums workflow and
signalsource. On SQLite an enum is a VARCHAR as long as its longest name, which FOLLOW does not lengthen, so only
PostgreSQL's named ENUM types change.
"""


async def add_follows(connection: AsyncConnection) -> None:
    """
    Version 4 to 5, first part: a run may follow another run's decisions. workflow_runs gains followed_run_id and
    trade_signals followed_decision_id, NULL for every existing row, and the workflow and signal source enums gain FOLLOW.
    """
    for statement in FOLLOW_STEP[connection.dialect.name]:
        await connection.execute(text(statement))


async def drop_yahoo_history(connection: AsyncConnection) -> None:
    """
    Version 4 to 5, second part: the history cache holds the broker's daily quotes, with each bar's change from its
    session's reference, instead of Yahoo's bars, which Yahoo adjusted for splits and capital reductions where the
    broker's are as traded. ohlcv_data is dropped with its Yahoo bars, which no read may mix with the broker's, and so are
    ohlcv_fetches and ohlcv_windows, which recorded each stock's Yahoo downloads where the broker answers one session
    of every stock at once. The next start's create_all makes ohlcv_data anew, and the cache fills it from the broker.
    """
    for name in ("ohlcv_windows", "ohlcv_fetches", "ohlcv_data"):
        await connection.execute(text(f"DROP TABLE IF EXISTS {name}"))


async def add_follows_and_drop_yahoo_history(connection: AsyncConnection) -> None:
    """
    Version 4 to 5, in two parts: add_follows, so a run may follow another run's decisions, then drop_yahoo_history, so
    the history cache holds the broker's daily quotes in place of Yahoo's bars. Version 5 is both, so one step runs them
    in the caller's transaction, and a failure in either leaves the database at version 4.
    """
    await add_follows(connection)
    await drop_yahoo_history(connection)


async def drop_buzz_strategy(connection: AsyncConnection) -> None:
    """
    Version 5 to 6: one strategy for the whole site. Buzz runs on the active strategy like every other workflow, so
    technical_settings loses buzz_strategy_id. Each owner keeps every strategy, the active one and the revision; only
    the separate Buzz choice goes. SQLite drops a column in place since 3.35, as PostgreSQL does.
    """
    await connection.execute(text("ALTER TABLE technical_settings DROP COLUMN buzz_strategy_id"))


ORDER_MODE_STEP = {
    "sqlite": ("ALTER TABLE workflow_runs DROP COLUMN order_mode",),
    "postgresql": ("ALTER TABLE workflow_runs DROP COLUMN order_mode", "DROP TYPE ordermode"),
}
"""drop_order_mode's statements per database backend: the column, and on PostgreSQL the ENUM type only it used."""


async def drop_order_mode(connection: AsyncConnection) -> None:
    """
    Version 6 to 7: each run chooses its broker when it starts, which workflow_runs.execution_provider records, so the
    installation's order mode, which every run copied from trading.order_mode, is gone, and workflow_runs.order_mode
    with it. No other table or column changes, so the step needs no data.
    """
    for statement in ORDER_MODE_STEP[connection.dialect.name]:
        await connection.execute(text(statement))


async def drop_ranking_records(connection: AsyncConnection) -> None:
    """
    Version 7 to 8: the site keeps no record of the ranking's decisions, so ranking_records, which version 7's startup
    created, is dropped with its rows. A database that never held it changes only its stamp.
    """
    await connection.execute(text("DROP TABLE IF EXISTS ranking_records"))


RANKING_FOLLOW_STEP = {
    "sqlite": (),
    "postgresql": ("ALTER TYPE workflow ADD VALUE 'RANKING_FOLLOW' AFTER 'FOLLOW'", "ALTER TYPE signalsource ADD VALUE 'RANKING'"),
}
"""
add_ranking_follow's statements per database backend. On SQLite an enum is a VARCHAR as long as its longest name, which
neither member lengthens, so only PostgreSQL's named ENUM types change.
"""


async def add_ranking_follow(connection: AsyncConnection) -> None:
    """
    Version 8 to 9: a run may follow the monthly ranking into the mock account, so the workflow enum gains
    RANKING_FOLLOW and the signal source enum RANKING. No table or column changes, and no row.
    """
    for statement in RANKING_FOLLOW_STEP[connection.dialect.name]:
        await connection.execute(text(statement))


type UpgradeStep = Callable[[AsyncConnection], Awaitable[None]]

UPGRADES: tuple[UpgradeStep, ...] = (
    record_run_failures,
    give_rows_their_owner,
    add_user_ai_model,
    add_follows_and_drop_yahoo_history,
    drop_buzz_strategy,
    drop_order_mode,
    drop_ranking_records,
    add_ranking_follow,
)
"""
The steps that upgrade an older database in place, oldest first: UPGRADES[n - 1] turns version n into version n + 1. A
step names the tables and columns it reads as they were at its version, never through today's SQLModel classes.
"""

SCHEMA_VERSION = len(UPGRADES) + 1
"""
The table layout and the stored meaning of every column this code writes. A change to an existing table, or to how a
column stores its value, appends its step to UPGRADES, which raises this; tests/test_schema_snapshot.py fails until it
does. A new table needs no step, because startup creates it. Before version 1, several tables stored Taiwan wall-clock
time in columns that are now read as UTC, so no step reaches version 1.
"""


def pending_steps(stamps: Sequence[int]) -> dict[str, UpgradeStep]:
    """
    The steps that bring a database stamped `stamps` to SCHEMA_VERSION, oldest first, each named `<from> -> <to>
    <function>`. None unless the database holds one stamp, of an older version that a step reaches.
    """
    if len(stamps) != 1 or not 1 <= stamps[0] < SCHEMA_VERSION:
        return {}

    return {
        f"{version} -> {version + 1} {step.__name__}": step for version, step in enumerate(UPGRADES[stamps[0] - 1 :], start=stamps[0])
    }


async def live_layout(connection: AsyncConnection) -> tuple[dict[str, frozenset[str]], list[int]]:
    """Each table's columns as the database holds them, and the schema version stamps, none while no stamp table exists."""

    def columns(sync_connection: Connection) -> dict[str, frozenset[str]]:
        tables = inspect(sync_connection)
        return {name: frozenset(column["name"] for column in tables.get_columns(name)) for name in tables.get_table_names()}

    live_columns = await connection.run_sync(columns)
    stamp_table = SQLModel.metadata.tables[SchemaVersionDTO.__tablename__]

    if stamp_table.name not in live_columns:
        return live_columns, []

    return live_columns, list((await connection.execute(select(stamp_table.c.version))).scalars())


async def upgrade(connection: AsyncConnection, stamps: Sequence[int]) -> None:
    """
    Upgrades a database of an older version, stamped `stamps`, in place to SCHEMA_VERSION, inside the caller's
    transaction. A step's own refusal, an OutdatedDatabaseError that says what to fix, goes on as it is; any other error
    is raised again naming the step. The restamp goes first: SQLite's driver begins its transaction at the first write,
    so an ALTER TABLE ahead of every write would commit at once and outlive a step that fails after it.
    """
    steps = pending_steps(stamps)
    stamp_table = SQLModel.metadata.tables[SchemaVersionDTO.__tablename__]
    await connection.execute(update(stamp_table).values(version=SCHEMA_VERSION))

    for name, step in steps.items():
        try:
            await step(connection)
        except OutdatedDatabaseError:
            raise
        except Exception as error:
            raise RuntimeError(f"The upgrade step {name} failed: {type(error).__name__}: {error}") from error
