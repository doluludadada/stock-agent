from collections.abc import Awaitable, Callable
from typing import ClassVar

from sqlalchemy import JSON, column, select, table, text, update
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlmodel import Field, SQLModel


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


UPGRADES: tuple[Callable[[AsyncConnection], Awaitable[None]], ...] = (record_run_failures,)
"""
The steps that upgrade an older database in place, oldest first: UPGRADES[n - 1] turns version n into version n + 1. A
step names the tables and columns it reads as they were at its version, never through today's SQLModel classes.
"""

SCHEMA_VERSION = len(UPGRADES) + 1
"""
The table layout and the stored meaning of every column this code writes. A change to an existing table, or to how a
column stores its value, appends its step to UPGRADES, which raises this. A new table needs no step, because startup
creates it. Before version 1, several tables stored Taiwan wall-clock time in columns that are now read as UTC, so no
step reaches version 1.
"""


async def upgrade(connection: AsyncConnection, version: int) -> None:
    """
    Upgrades a database of an older `version` in place to SCHEMA_VERSION, inside the caller's transaction. The restamp
    goes first: SQLite's driver begins its transaction at the first write, so an ALTER TABLE ahead of every write would
    commit at once and outlive a step that fails after it.
    """
    stamp_table = SQLModel.metadata.tables[SchemaVersionDTO.__tablename__]
    await connection.execute(update(stamp_table).values(version=SCHEMA_VERSION))

    for step in UPGRADES[version - 1 :]:
        await step(connection)
