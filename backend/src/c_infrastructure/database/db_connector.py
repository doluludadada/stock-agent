from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from copy import copy
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Self, override

import sqlalchemy
from sqlalchemy import event, func, select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from a_domain.ports.system.database_connector import DatabaseMigration, DatabaseState, IDatabaseConnector
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import DatabaseBackend
from a_domain.types.errors import SignInRequired
from a_domain.types.ids import UserId
from b_application.config.app_config import AppConfig
from c_infrastructure.database.models.backups import DatabaseCommandError, copy_sqlite, run_postgresql_client
from c_infrastructure.database.models.owned_rows import OWNER_COLUMN, guard_session
from c_infrastructure.database.models.schema_version_dto import (
    SCHEMA_VERSION,
    OutdatedDatabaseError,
    SchemaVersionDTO,
    live_layout,
    pending_steps,
    upgrade,
)


class DatabaseConnector(IDatabaseConnector[AsyncSession]):
    """The explicitly selected local SQLite or service PostgreSQL database; credentials never select the backend."""

    def __init__(self, config: AppConfig, logger: ILoggingProvider) -> None:
        self._logger = logger
        self._db = config.db
        self._backups = config.project_root / "backups"
        self._sqlite_path: Path | None = None
        self._owner_id: UserId | None = None

        if config.db.backend == DatabaseBackend.POSTGRESQL:
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
            # SQLite ignores foreign keys unless each connection turns them on; PostgreSQL always checks them.
            event.listen(
                self._engine.sync_engine, "connect", lambda connection, _: connection.cursor().execute("PRAGMA foreign_keys=ON")
            )

        self._session_factory = async_sessionmaker(bind=self._engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)

    @override
    async def init_db(self) -> None:
        """
        Create the tables that do not exist yet; a new database first gets its schema version stamp. Raise
        OutdatedDatabaseError, and change nothing, when the database is not new and its stamp is not SCHEMA_VERSION, an
        older version included, or when an existing table's columns differ from its SQLModel class. Startup never
        upgrades a database: `just db-migrate` does, after a backup.
        """
        stamp_table = SQLModel.metadata.tables[SchemaVersionDTO.__tablename__]

        async with self._engine.begin() as connection:
            live_columns, stamps = await live_layout(connection)

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
        if pending_steps(stamps):
            return (
                f"The database is at schema version {stamps[0]}, and this version of stock-agent needs {SCHEMA_VERSION}. "
                "Startup never upgrades a database.\nRemedy: run `just db-migrate`. It backs the database up into backups/ "
                "first, then upgrades it in one transaction. `just db-status` shows the steps it runs."
            )

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
                "The database has tables from another version of stock-agent that startup cannot upgrade in place:",
                *(f"  - {table}" for table in outdated),
                *version,
                f"Remedy: {reset}drop the tables named above. The next start recreates them empty.",
                "Cached prices and EPS refill themselves; mock account, watchlist and trading rows in a dropped table are lost.",
            ]
        )

    @override
    async def state(self) -> DatabaseState:
        live_columns: dict[str, frozenset[str]] = {}
        stamps: list[int] = []
        rows: dict[str, int] = {}

        if self._sqlite_path is None or self._sqlite_path.exists():
            async with self._engine.connect() as connection:
                live_columns, stamps = await live_layout(connection)
                rows = {
                    name: (await connection.scalar(select(func.count()).select_from(sqlalchemy.table(name)))) or 0
                    for name in sorted(live_columns)
                }

        pending = tuple(pending_steps(stamps))
        outdated = self.outdated_tables(live_columns, stamps)

        return DatabaseState(
            backend=self._db.backend,
            location=str(self._sqlite_path or f"{self._db.user}@{self._db.host}:{self._db.port}/{self._db.name}"),
            stamps=tuple(stamps),
            required=SCHEMA_VERSION,
            pending=pending,
            rows=rows,
            refusal=self.outdated_message(outdated, stamps) if outdated else None,
        )

    @override
    async def backup(self) -> Path:
        stamps = (await self.state()).stamps
        self._backups.mkdir(exist_ok=True)
        self._backups.chmod(0o700)
        taken = f"{datetime.now(UTC):%Y%m%d-%H%M%S}"
        version = "-".join(str(stamp) for stamp in stamps) or "none"
        stem, suffix = (self._db.name, "dump") if self._sqlite_path is None else ("stock_agent", "db")
        names = (f"{stem}.{taken}{f'-{attempt}' if attempt > 1 else ''}.v{version}.{suffix}" for attempt in count(1))
        destination = next(path for path in (self._backups / name for name in names) if not path.exists())
        destination.touch(mode=0o600, exist_ok=False)

        try:
            if self._sqlite_path is None:
                await run_postgresql_client("pg_dump", self._db, "--format=custom", f"--file={destination}")
            else:
                await copy_sqlite(self._sqlite_path, destination)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

        return destination

    @override
    async def migrate(self) -> DatabaseMigration:
        before = await self.state()

        if before.refusal is not None and not before.pending:
            raise OutdatedDatabaseError(before.refusal)

        if not before.pending:
            return DatabaseMigration(backup=None, before=before, after=before)

        backup = await self.backup()

        try:
            async with self._engine.begin() as connection:
                await upgrade(connection, before.stamps)
                live_columns, stamps = await live_layout(connection)

                if outdated := self.outdated_tables(live_columns, stamps):
                    raise OutdatedDatabaseError(self.outdated_message(outdated, stamps))

        except Exception as error:
            raise DatabaseCommandError(
                f"{error}\nThe upgrade rolled back: the database is still at version {before.stamps[0]} with every row it "
                f"had. Its backup from before the upgrade: {backup}"
            ) from error

        return DatabaseMigration(backup=backup, before=before, after=await self.state())

    @override
    async def restore(self, backup: Path) -> Path | None:
        header = b"PGDMP" if self._sqlite_path is None else b"SQLite format 3\x00"

        if not backup.is_file():
            raise DatabaseCommandError(f"There is no file at {backup}. Nothing changed.")

        with backup.open("rb") as file:
            if file.read(len(header)) != header:
                raise DatabaseCommandError(f"{backup} is not a backup of a {self._db.backend.value} database. Nothing changed.")

        current = await self.backup() if (await self.state()).rows else None

        if self._sqlite_path is None:
            await run_postgresql_client(
                "pg_restore", self._db, "--clean", "--if-exists", "--single-transaction", "--no-owner", str(backup)
            )
        else:
            await copy_sqlite(backup, self._sqlite_path)

        return current

    @override
    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession]:
        """A transactional scope over the shared tables. A statement or flush on an owned table raises."""
        async with self._session_factory() as session:
            guard_session(session.sync_session)

            try:
                yield session
            except Exception as error:
                await session.rollback()
                self._logger.error(f"Database session rollback due to error: {error}")
                raise
            finally:
                await session.close()

    @override
    def for_owner(self, owner_id: UserId | None) -> Self:
        """A copy that shares this connector's engine and its pool."""
        bound = copy(self)
        bound._owner_id = owner_id
        return bound

    @property
    @override
    def owner_id(self) -> UserId:
        if self._owner_id is None:
            raise SignInRequired("Sign in first.")

        return self._owner_id

    @override
    @asynccontextmanager
    async def owner_session(self) -> AsyncGenerator[AsyncSession]:
        """A transactional scope over the bound owner's rows."""
        owner_id = self.owner_id

        async with self.get_session() as session:
            session.info[OWNER_COLUMN] = owner_id
            yield session

    @override
    async def close(self) -> None:
        """Dispose of the engine and all connections."""
        try:
            self._logger.debug("Closing database engine...")
            await self._engine.dispose()
        except Exception:
            pass
