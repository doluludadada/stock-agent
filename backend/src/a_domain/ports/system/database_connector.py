from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol


class IDatabaseConnector[Session](Protocol):
    """
    The database the repositories share. Startup checks it and creates the missing tables; each unit of work gets its own
    session. The infrastructure names the session type, so this port never imports a database library.
    """

    async def init_db(self) -> None:
        """
        Creates the tables that do not exist yet, stamping a new database with the code's schema version, after
        upgrading a database of an older version in place and refusing one whose stamp or tables do not match the code.
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

    def get_session(self) -> AbstractAsyncContextManager[Session]: ...

    async def close(self) -> None: ...
