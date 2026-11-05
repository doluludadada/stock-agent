from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Protocol, Self

from pydantic.dataclasses import dataclass

from a_domain.types.enums import DatabaseBackend
from a_domain.types.ids import UserId


@dataclass(frozen=True)
class DatabaseState:
    """What `just db-status` shows: where the database is, its schema version and the code's, and each table's rows."""

    backend: DatabaseBackend
    location: str
    """The SQLite file, or the PostgreSQL user, server and database name. Never a password."""

    stamps: tuple[int, ...]
    """The schema version rows. A database startup created holds one; a new database holds none."""

    required: int
    """The schema version this code needs."""

    pending: tuple[str, ...]
    """The upgrade steps `just db-migrate` would run, oldest first, as `<from> -> <to> <name>`."""

    rows: dict[str, int]
    """Every table's row count, by table name, including tables the code no longer declares."""

    refusal: str | None
    """Why startup refuses the database, or None when startup opens it."""


@dataclass(frozen=True)
class DatabaseMigration:
    """One `just db-migrate`: the backup made first, and the database before and after the upgrade steps."""

    backup: Path | None
    """None when no step was pending, so nothing was backed up or changed."""

    before: DatabaseState
    after: DatabaseState


class IDatabaseConnector[Session](Protocol):
    """
    The database the repositories share. Startup checks it and creates the missing tables; each unit of work gets its own
    session. The infrastructure names the session type, so this port never imports a database library.

    An owned table is a table with an owner_id column: it holds users' rows. Its rows are reachable only through the
    owner_session of a connector bound to that owner by for_owner, and only that owner's; get_session serves the shared
    tables. dependencies.py binds one connector per owner and hands it to every adapter that holds that owner's data, so
    no adapter names an owner itself.
    """

    async def init_db(self) -> None:
        """
        Creates the tables that do not exist yet, stamping a new database with the code's schema version. Refuses, and
        changes nothing, a database whose stamp or tables do not match the code, one of an older version included:
        `just db-migrate` upgrades that one, after a backup.
        """
        ...

    async def state(self) -> DatabaseState:
        """Reads the database without changing it. A SQLite file that does not exist yet reads as a new database."""
        ...

    async def backup(self) -> Path:
        """
        Copies the whole database into backups/ at the project root (created owner-only), named after the database, the
        UTC time and its schema version, and returns the copy's path.
        """
        ...

    async def migrate(self) -> DatabaseMigration:
        """
        Backs the database up, then runs the pending upgrade steps and checks the tables against the code, all in one
        transaction. With no step pending it changes nothing and makes no backup; a database no step upgrades raises
        OutdatedDatabaseError. A failure after the backup rolls the transaction back, so the database keeps its version
        and rows, and raises DatabaseCommandError naming what failed and the backup.
        """
        ...

    async def restore(self, backup: Path) -> Path | None:
        """
        Backs the current database up, then replaces it with `backup`, a backup of the same backend, which stays where it
        is. Returns the backup made first, None when the database had no table to back up. Refuses a file that is not a
        backup of this backend before changing anything.
        """
        ...

    def outdated_tables(self, live_columns: Mapping[str, frozenset[str]], stamps: Sequence[int]) -> list[str]:
        """
        The existing tables startup must refuse, given each live table's columns and the stored schema version stamps:
        every table when the database is not new and its stamp is not the code's, else each table whose columns differ.
        A table whose columns differ is described with those columns.
        """
        ...

    def outdated_message(self, outdated: list[str], stamps: Sequence[int]) -> str:
        """What the user reads when startup refuses the database: the outdated tables, the stamp found, and the remedy."""
        ...

    def get_session(self) -> AbstractAsyncContextManager[Session]:
        """The shared tables. A statement or flush that touches an owned table raises."""
        ...

    def for_owner(self, owner_id: UserId | None) -> Self:
        """
        The same database, bound to one owner. None binds no one: the connector of a signed-out pipeline, whose
        owner_session and owner_id raise SignInRequired before any SQL.
        """
        ...

    @property
    def owner_id(self) -> UserId:
        """The bound owner, whom every row an owned adapter writes names. Raises SignInRequired when none is bound."""
        ...

    def owner_session(self) -> AbstractAsyncContextManager[Session]:
        """
        The bound owner's rows only. Every read, update and delete of an owned table is limited to the owner's rows,
        and an insert or flush of a row naming another owner raises. A merge of another owner's primary key fails on
        the key instead of overwriting that row. Raises SignInRequired when no owner is bound.
        """
        ...

    async def close(self) -> None: ...
