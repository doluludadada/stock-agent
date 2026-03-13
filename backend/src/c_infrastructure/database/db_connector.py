from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.config import AppConfig


class DatabaseConnector:
    """
    Unified Async Database Connector.
    Defaults to local SQLite (aiosqlite).
    Switches to PostgreSQL (asyncpg) if credentials exist in AppConfig.
    """

    def __init__(self, config: AppConfig, logger: ILoggingProvider):
        self._logger = logger

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
            sqlite_path = config.project_root / "stock_agent.db"
            connection_url = f"sqlite+aiosqlite:///{sqlite_path}"
            self._engine = create_async_engine(connection_url, echo=False)

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    async def init_db(self) -> None:
        """Create tables if they don't exist based on SQLModel metadata."""
        async with self._engine.begin() as conn:
            self._logger.debug("Running DB schema creation...")
            await conn.run_sync(SQLModel.metadata.create_all)

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
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
