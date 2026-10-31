from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import override

from sqlalchemy import inspect, select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from a_domain.ports.system.database_connector import IDatabaseConnector
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.config.app_config import AppConfig
from c_infrastructure.database.models.schema_version_dto import SCHEMA_VERSION, SchemaVersionDTO


class OutdatedDatabaseError(RuntimeError):
    """
    The database holds tables of another schema version, or of none, or a table with columns other than its SQLModel
    class declares. create_all never alters an existing table.
    """


class DatabaseConnector(IDatabaseConnector[AsyncSession]):
    """Local SQLite (aiosqlite) by default; PostgreSQL (asyncpg) when AppConfig has its credentials."""

    def __init__(self, config: AppConfig, logger: ILoggingProvider) -> None:
        self._logger = logger
        self._sqlite_path: Path | None = None

        if all([config.db.user, config.db.password, config.db.host, config.db.name]):
            self._logger.info("Initialising PostgreSQL (asyncpg) connection...")
            connection_url = URL.create(
                drivername="postgresql+asyncpg",
                username=config.db.user,
                password=config.db.password,
                host=config.db.host,
                port=config.db.port,
                database=config.db.name,
            )
            self._engine = create_async_engine(connection_url, echo=False, pool_pre_ping=True)
        else:
            self._logger.info("Initialising local SQLite (aiosqlite) connection...")
            self._sqlite_path = config.project_root / "stock_agent.db"
            self._engine = create_async_engine(f"sqlite+aiosqlite:///{self._sqlite_path}", echo=False)

        self._session_factory = async_sessionmaker(bind=self._engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)

    @override
    async def init_db(self) -> None:
        """
        Create the tables that do not exist yet; a new database first gets its schema version stamp. Raise
        OutdatedDatabaseError, and change nothing, when the database is not new and its stamp is missing or another
        version's, or when an existing table's columns differ from its SQLModel class.
        """
        stamp_table = SQLModel.metadata.tables[SchemaVersionDTO.__tablename__]

        async with self._engine.begin() as connection:
            live_columns = await connection.run_sync(
                lambda sync_connection: {
                    table: frozenset(column["name"] for column in inspect(sync_connection).get_columns(table))
                    for table in inspect(sync_connection).get_table_names()
                }
            )
            stamps = (
                list((await connection.execute(select(stamp_table.c.version))).scalars()) if stamp_table.name in live_columns else []
            )

            if outdated := self.outdated_tables(live_columns, stamps):
                raise OutdatedDatabaseError(self.outdated_message(outdated, stamps))

            if not stamps:
                # A database with tables and no stamp is refused, so the stamp goes in before any other table.
                await connection.run_sync(SQLModel.metadata.create_all, tables=[stamp_table])
                await connection.execute(stamp_table.insert().values(version=SCHEMA_VERSION))

            self._logger.debug("Running DB schema creation...")
            await connection.run_sync(SQLModel.metadata.create_all)

    @override
    def outdated_tables(self, live_columns: Mapping[str, frozenset[str]], stamps: Sequence[int]) -> list[str]:
        existing = [table for table in SQLModel.metadata.sorted_tables if table.name in live_columns]

        if not stamps and all(table.name == SchemaVersionDTO.__tablename__ for table in existing):
            return []

        is_current = list(stamps) == [SCHEMA_VERSION]
        outdated = []

        for table in existing:
            declared = frozenset(column.name for column in table.columns)
            live = live_columns[table.name]

            if declared != live:
                missing = ", ".join(sorted(declared - live)) or "none"
                unused = ", ".join(sorted(live - declared)) or "none"
                outdated.append(f"{table.name} (missing columns: {missing}; columns no longer used: {unused})")
            elif not is_current:
                outdated.append(table.name)

        return outdated

    @override
    def outdated_message(self, outdated: list[str], stamps: Sequence[int]) -> str:
        reset = f"delete {self._sqlite_path}, or " if self._sqlite_path else ""
        found = ", ".join(str(stamp) for stamp in stamps) or "none"
        version = (
            []
            if list(stamps) == [SCHEMA_VERSION]
            else [
                f"The database's schema version is {found}, and this version of stock-agent needs {SCHEMA_VERSION}. Rows of "
                "another version can store the same columns differently, so a table whose columns match must go too."
            ]
        )

        return "\n".join(
            [
                "The database has tables from an older version of stock-agent, and startup never alters a table:",
                *(f"  - {table}" for table in outdated),
                *version,
                f"Remedy: {reset}drop the tables named above. The next start recreates them empty.",
                "Cached prices and EPS refill themselves; mock account, watchlist and trading rows in a dropped table are lost.",
            ]
        )

    @override
    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession]:
        """Provide a transactional scope around a series of operations."""
        async with self._session_factory() as session:
            try:
                yield session
            except Exception as error:
                await session.rollback()
                self._logger.error(f"Database session rollback due to error: {error}")
                raise
            finally:
                await session.close()

    @override
    async def close(self) -> None:
        """Dispose of the engine and all connections."""
        try:
            self._logger.debug("Closing database engine...")
            await self._engine.dispose()
        except Exception:
            pass
