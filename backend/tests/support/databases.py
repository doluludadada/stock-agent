"""
A real database of each backend for tests of the SQL adapters: a SQLite file always, and PostgreSQL when
STOCK_AGENT_TEST_POSTGRES_URL names a database the tests may empty (for example
postgresql://shiou:trial@localhost:5432/stock_agent_accounts_trial). Every PostgreSQL test starts from an empty schema.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import Connection, inspect, make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from trading_stack import SilentLogger

from a_domain.types.enums import DatabaseBackend
from b_application.config.app_config import AppConfig, DbConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from support.settings import shipped_config

POSTGRES_URL = os.environ.get("STOCK_AGENT_TEST_POSTGRES_URL")
SCHEMA_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "schema"

BACKENDS = [
    pytest.param(DatabaseBackend.SQLITE, id="sqlite"),
    pytest.param(
        DatabaseBackend.POSTGRESQL,
        id="postgresql",
        marks=pytest.mark.skipif(POSTGRES_URL is None, reason="STOCK_AGENT_TEST_POSTGRES_URL is not set"),
    ),
]


def database_config(backend: DatabaseBackend, folder: Path) -> AppConfig:
    """The shipped settings over a SQLite file in folder, or over the test PostgreSQL database."""
    config = shipped_config(folder)

    if backend == DatabaseBackend.SQLITE:
        return config

    assert POSTGRES_URL is not None
    url = make_url(POSTGRES_URL)
    credentials = {"DB_USER": url.username, "DB_PASSWORD": url.password or "trial", "DB_HOST": url.host, "DB_NAME": url.database}
    db = DbConfig(
        backend=DatabaseBackend.POSTGRESQL, chroma_persist_path=str(folder / "chroma"), DB_PORT=url.port or 5432, **credentials
    )
    return config.model_copy(update={"db": db})


async def empty_database(backend: DatabaseBackend, folder: Path) -> DatabaseConnector:
    """A connector to an empty database of the backend: a new SQLite file, or the test PostgreSQL database emptied."""
    if backend == DatabaseBackend.POSTGRESQL:
        assert POSTGRES_URL is not None
        engine = create_async_engine(make_url(POSTGRES_URL).set(drivername="postgresql+asyncpg"))

        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))

        await engine.dispose()

    return DatabaseConnector(config=database_config(backend, folder), logger=SilentLogger())


def raw_engine(backend: DatabaseBackend, folder: Path) -> AsyncEngine:
    """An engine on the same database a connector of database_config opens, for a test to build or read tables itself."""
    if backend == DatabaseBackend.SQLITE:
        return create_async_engine(f"sqlite+aiosqlite:///{folder / 'stock_agent.db'}")

    assert POSTGRES_URL is not None
    return create_async_engine(make_url(POSTGRES_URL).set(drivername="postgresql+asyncpg"))


async def create_version_2_tables(backend: DatabaseBackend, folder: Path, stamp: int = 2) -> None:
    """Every table as schema version 2 created it on the backend (fixtures/schema, written by that version's create_all)."""
    statements = (SCHEMA_FIXTURES / f"version_2.{backend.value}.sql").read_text().split(";\n\n")
    engine = raw_engine(backend, folder)

    async with engine.begin() as connection:
        for statement in statements:
            await connection.execute(text(statement.strip().removesuffix(";")))

        await connection.execute(text("INSERT INTO schema_version (version) VALUES (:stamp)"), {"stamp": stamp})

    await engine.dispose()


async def create_version_1_tables(backend: DatabaseBackend, folder: Path) -> None:
    """
    Every table as schema version 1 created it, stamped 1. On SQLite, the tables of a database the app wrote on
    2026-11-04 (fixtures/schema/version_1.sqlite.sql, its schema only). No version 1 database on PostgreSQL was kept, so
    there it is version 2's tables without workflow_runs.failure, the one column version 2 added.
    """
    if backend == DatabaseBackend.POSTGRESQL:
        await create_version_2_tables(backend, folder, stamp=1)
        statements = ["ALTER TABLE workflow_runs DROP COLUMN failure"]
    else:
        statements = [*(SCHEMA_FIXTURES / "version_1.sqlite.sql").read_text().split(";\n\n"), "INSERT INTO schema_version VALUES (1)"]

    engine = raw_engine(backend, folder)

    async with engine.begin() as connection:
        for statement in statements:
            await connection.execute(text(statement.strip().removesuffix(";")))

    await engine.dispose()


async def database_snapshot(backend: DatabaseBackend, folder: Path) -> dict[str, tuple[list[str], list[tuple[str, ...]]]]:
    """Every table's columns and rows, as text, and so the stamp: what a command that changed nothing must leave as it was."""

    def snapshot_of(connection: Connection) -> dict[str, tuple[list[str], list[tuple[str, ...]]]]:
        tables = inspect(connection)
        dump = {}

        for table in sorted(tables.get_table_names()):
            columns = sorted(column["name"] for column in tables.get_columns(table))
            rows = connection.execute(text(f"SELECT {', '.join(columns)} FROM {table}"))
            dump[table] = (columns, sorted(tuple(str(value) for value in row) for row in rows))

        return dump

    engine = raw_engine(backend, folder)

    async with engine.connect() as connection:
        dump = await connection.run_sync(snapshot_of)

    await engine.dispose()
    return dump
