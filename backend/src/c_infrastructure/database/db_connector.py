from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.engine import URL, Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.config import AppConfig


class OutdatedDatabaseError(RuntimeError):
    """A table exists with columns other than its SQLModel class declares. create_all never alters an existing table."""


def outdated_tables(connection: Connection) -> list[str]:
    """Each existing table whose columns differ from its SQLModel class, described with the columns that differ."""
    inspector = inspect(connection)
    existing = set(inspector.get_table_names())
    outdated = []

    for table in SQLModel.metadata.sorted_tables:
        if table.name not in existing:
            continue

        declared = {column.name for column in table.columns}
        live = {column["name"] for column in inspector.get_columns(table.name)}

        if declared != live:
            missing = ", ".join(sorted(declared - live)) or "none"
            unused = ", ".join(sorted(live - declared)) or "none"
            outdated.append(f"{table.name} (missing columns: {missing}; columns no longer used: {unused})")

    return outdated


class DatabaseConnector:
    """
    Unified Async Database Connector.
    Defaults to local SQLite (aiosqlite).
    Switches to PostgreSQL (asyncpg) if credentials exist in AppConfig.
    """

    def __init__(self, config: AppConfig, logger: ILoggingProvider):
        self._logger = logger
        self._sqlite_path: Path | None = None

        # Check if all required Postgres credentials are provided
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
            connection_url = f"sqlite+aiosqlite:///{self._sqlite_path}"
            self._engine = create_async_engine(connection_url, echo=False)

        self._session_factory = async_sessionmaker(bind=self._engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)

    async def init_db(self) -> None:
        """
        Create the tables that do not exist yet. Raise OutdatedDatabaseError, and change nothing, when an existing
        table's columns differ from its SQLModel class: saving to that table would fail on every write.
        """
        async with self._engine.begin() as conn:
            outdated = await conn.run_sync(outdated_tables)

            if outdated:
                raise OutdatedDatabaseError(self._outdated_message(outdated))

            self._logger.debug("Running DB schema creation...")
            await conn.run_sync(SQLModel.metadata.create_all)

    def _outdated_message(self, outdated: list[str]) -> str:
        reset = f"delete {self._sqlite_path}, or " if self._sqlite_path else ""

        return "\n".join(
            [
                "The database has tables from an older version of stock-agent, and startup never alters a table:",
                *(f"  - {table}" for table in outdated),
                f"Remedy: {reset}drop the tables named above. The next start recreates them empty.",
                "Cached prices and EPS refill themselves; mock account, watchlist and trading rows in a dropped table are lost.",
            ]
        )

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession]:
        """Provide a transactional scope around a series of operations."""
        async with self._session_factory() as session:
            try:
                yield session
            except Exception as e:
                await session.rollback()
                self._logger.error(f"Database session rollback due to error: {e}")
                raise
            finally:
                await session.close()

    async def close(self) -> None:
        """Dispose of the engine and all connections."""
        if not hasattr(self, "_engine"):
            return
        try:
            self._logger.debug("Closing database engine...")
            await self._engine.dispose()
        except Exception:
            pass
