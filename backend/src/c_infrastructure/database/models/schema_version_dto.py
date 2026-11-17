from collections.abc import Awaitable, Callable, Sequence
from typing import ClassVar

from sqlalchemy import Connection, inspect, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlmodel import Field, SQLModel


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


type UpgradeStep = Callable[[AsyncConnection], Awaitable[None]]

FIRST_SCHEMA_VERSION = 9
"""
The schema version of the first tables an upgrade starts from: the ones the first deployed site holds. No released
version created an earlier layout, so no step reaches below it and a database stamped lower is refused.
"""


async def add_the_ranking_formula_of_a_run(connection: AsyncConnection) -> None:
    """Version 9 to 10: a workflow run keeps the ranking formula a ranking follow used. Every run before it has none."""
    await connection.execute(text("ALTER TABLE workflow_runs ADD COLUMN ranking_formula JSON"))


async def add_the_schedule_of_the_ranking_follow(connection: AsyncConnection) -> None:
    """
    Version 10 to 11: a user keeps the time of their scheduled ranking follow, none for every user before it, and a
    workflow run the decision a ranking follow took and whether the schedule started it, which no run before it did.
    """
    await connection.execute(text("ALTER TABLE users ADD COLUMN ranking_follow_time TIME"))
    await connection.execute(text("ALTER TABLE workflow_runs ADD COLUMN ranking_decided_on DATE"))
    await connection.execute(text("ALTER TABLE workflow_runs ADD COLUMN scheduled BOOLEAN NOT NULL DEFAULT false"))
    await connection.execute(text("ALTER TABLE workflow_runs ALTER COLUMN scheduled DROP DEFAULT"))


async def add_what_a_ranking_follow_left_open(connection: AsyncConnection) -> None:
    """
    Version 11 to 12: a workflow run keeps how many stocks a ranking follow still had to trade at its last look. Every
    run before it has none, so the schedule counts none of them as a finished follow of its decision.
    """
    await connection.execute(text("ALTER TABLE workflow_runs ADD COLUMN ranking_open INTEGER"))


async def add_the_account_of_the_scheduled_follow(connection: AsyncConnection) -> None:
    """
    Version 12 to 13: a user keeps the account their scheduled ranking follow orders on, the mock account for every
    user before it, which is where every schedule followed until now. The column's type is the one workflow_runs
    names a run's broker with.
    """
    await connection.execute(text("ALTER TABLE users ADD COLUMN ranking_follow_broker executionprovider NOT NULL DEFAULT 'MOCK'"))
    await connection.execute(text("ALTER TABLE users ALTER COLUMN ranking_follow_broker DROP DEFAULT"))


UPGRADES: tuple[UpgradeStep, ...] = (
    add_the_ranking_formula_of_a_run,
    add_the_schedule_of_the_ranking_follow,
    add_what_a_ranking_follow_left_open,
    add_the_account_of_the_scheduled_follow,
)
"""
The steps that upgrade an older database in place, oldest first: UPGRADES[n] turns version FIRST_SCHEMA_VERSION + n
into the next. A step names the tables and columns it reads as they were at its version, never through today's SQLModel
classes.
"""

SCHEMA_VERSION = FIRST_SCHEMA_VERSION + len(UPGRADES)
"""
The table layout and the stored meaning of every column this code writes. A change to an existing table, or to how a
column stores its value, appends its step to UPGRADES, which raises this; tests/test_schema_snapshot.py fails until it
does. A new table needs no step, because startup creates it.
"""


def pending_steps(stamps: Sequence[int]) -> dict[str, UpgradeStep]:
    """
    The steps that bring a database stamped `stamps` to the code's version, oldest first, each named `<from> -> <to>
    <function>`. None unless the database holds one stamp, of an older version that a step reaches.
    """
    if len(stamps) != 1 or not FIRST_SCHEMA_VERSION <= stamps[0] < FIRST_SCHEMA_VERSION + len(UPGRADES):
        return {}

    return {
        f"{version} -> {version + 1} {step.__name__}": step
        for version, step in enumerate(UPGRADES[stamps[0] - FIRST_SCHEMA_VERSION :], start=stamps[0])
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
    Upgrades a database of an older version, stamped `stamps`, in place to the code's version, inside the caller's
    transaction, which PostgreSQL rolls back whole, DDL included, when a step fails. A step's own refusal, an
    OutdatedDatabaseError that says what to fix, goes on as it is; any other error is raised again naming the step.
    """
    steps = pending_steps(stamps)
    stamp_table = SQLModel.metadata.tables[SchemaVersionDTO.__tablename__]
    await connection.execute(update(stamp_table).values(version=stamps[0] + len(steps)))

    for name, step in steps.items():
        try:
            await step(connection)
        except OutdatedDatabaseError:
            raise
        except Exception as error:
            raise RuntimeError(f"The upgrade step {name} failed: {type(error).__name__}: {error}") from error
