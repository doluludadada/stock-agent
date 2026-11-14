"""
The PostgreSQL database the tests run on. A test session owns one throwaway database, stock_agent_test_<process id>,
which it creates on the server at 127.0.0.1:5432 as the role stock_agent_test and drops when it ends, and every test
that opened it leaves it for the next one emptied. The role is the only setup (README.md, "Tests"): it may create
databases and owns none but the sessions', so no test reaches a database of the app or of another project.
"""

import asyncio
import os
from pathlib import Path

import asyncpg
from sqlalchemy import Connection, Engine, event, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from trading_stack import SilentLogger

from c_infrastructure.database.db_connector import DatabaseConnector
from support.settings import shipped_config

TEST_ROLE = "stock_agent_test"
"""The role's name and its password, which a server that trusts loopback connections never asks for."""

TEST_DATABASE_PREFIX = f"{TEST_ROLE}_"
SERVER = {"host": "127.0.0.1", "port": 5432, "user": TEST_ROLE, "password": TEST_ROLE}
ENVIRONMENT = {
    "DB_USER": TEST_ROLE,
    "DB_PASSWORD": TEST_ROLE,
    "DB_HOST": SERVER["host"],
    "DB_PORT": str(SERVER["port"]),
    "DB_NAME": f"{TEST_DATABASE_PREFIX}{os.getpid()}",
}
"""The database settings every test's configuration reads: the session's own database."""

SETUP = (
    f"The tests need PostgreSQL at {SERVER['host']}:{SERVER['port']} and the role {TEST_ROLE}, which may create "
    f"databases. Create it once: psql -d postgres -c \"CREATE ROLE {TEST_ROLE} LOGIN CREATEDB PASSWORD '{TEST_ROLE}'\""
)


class TestDatabase:
    """The session's database, and whether a test has opened it since it was last emptied."""

    __test__ = False

    def __init__(self) -> None:
        self.name = ENVIRONMENT["DB_NAME"]
        self.opened = False
        event.listen(Engine, "connect", self.mark_opened)

    def mark_opened(self, *_: object) -> None:
        self.opened = True

    def create(self) -> None:
        """Creates the database, after dropping what a session that was killed left behind."""
        try:
            asyncio.run(self.recreate())
        except (OSError, asyncpg.PostgresError) as error:
            raise RuntimeError(f"{SETUP}\n{type(error).__name__}: {error}") from error

    async def recreate(self) -> None:
        server = await asyncpg.connect(database="postgres", **SERVER)

        try:
            for name in await server.fetch("SELECT datname FROM pg_database WHERE datname LIKE $1", f"{TEST_DATABASE_PREFIX}%"):
                if name["datname"] == self.name or not process_runs(
                    name["datname"].removeprefix(TEST_DATABASE_PREFIX).partition("_")[0]
                ):
                    await server.execute(f'DROP DATABASE "{name["datname"]}" WITH (FORCE)')

            await server.execute(f'CREATE DATABASE "{self.name}"')
        finally:
            await server.close()

    def empty(self) -> None:
        """Leaves no table, type or row, and no connection a test left open, if a test opened the database."""
        if self.opened:
            asyncio.run(self.drop_everything())
            self.opened = False

    async def drop_everything(self) -> None:
        database = await asyncpg.connect(database=self.name, **SERVER)

        try:
            await database.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
            )
            await database.execute("DROP SCHEMA public CASCADE")
            await database.execute("CREATE SCHEMA public")
        finally:
            await database.close()

    def drop(self) -> None:
        asyncio.run(self.drop_database())

    async def drop_database(self) -> None:
        server = await asyncpg.connect(database="postgres", **SERVER)

        try:
            await server.execute(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)')
        finally:
            await server.close()


def process_runs(process_id: str) -> bool:
    """Whether the process that named a test database after itself still runs, so its databases are left alone."""
    if not process_id.isdecimal():
        return False

    try:
        os.kill(int(process_id), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

    return True


def open_database(folder: Path) -> DatabaseConnector:
    """A connector to the session's database, which starts every test empty, over the shipped settings rooted at folder."""
    return DatabaseConnector(config=shipped_config(folder), logger=SilentLogger())


def raw_engine() -> AsyncEngine:
    """An engine on the session's database, for a test to build or read tables itself."""
    return create_async_engine(
        f"postgresql+asyncpg://{TEST_ROLE}:{TEST_ROLE}@{SERVER['host']}:{SERVER['port']}/{ENVIRONMENT['DB_NAME']}"
    )


async def execute(*statements: str) -> None:
    engine = raw_engine()

    async with engine.begin() as connection:
        for statement in statements:
            await connection.execute(text(statement))

    await engine.dispose()


async def database_snapshot() -> dict[str, tuple[list[str], list[tuple[str, ...]]]]:
    """Every table's columns and rows, as text, and so the stamp: what a command that changed nothing must leave as it was."""

    def snapshot_of(connection: Connection) -> dict[str, tuple[list[str], list[tuple[str, ...]]]]:
        tables = inspect(connection)
        dump = {}

        for table in sorted(tables.get_table_names()):
            columns = sorted(column["name"] for column in tables.get_columns(table))
            rows = connection.execute(text(f"SELECT {', '.join(columns)} FROM {table}"))
            dump[table] = (columns, sorted(tuple(str(value) for value in row) for row in rows))

        return dump

    engine = raw_engine()

    async with engine.connect() as connection:
        dump = await connection.run_sync(snapshot_of)

    await engine.dispose()
    return dump
