"""
The database commands: `just db-status`, `just db-backup`, `just db-migrate` and `just db-restore <backup> --yes`. Each
opens only the configured database, never the trading setup, the accounts key or a broker, so it also works on a database
that startup refuses. docs/database-migrations.md describes them.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from rich.table import Table

from a_domain.ports.system.database_connector import DatabaseState, IDatabaseConnector
from c_infrastructure.database.db_connector import DatabaseCommandError
from d_presentation.cli import terminal
from d_presentation.dependencies import STARTUP_REFUSALS, open_database

type Database = IDatabaseConnector[Any]


def say(line: str, style: str | None = None) -> None:
    """A line as it is: no markup read from a path, and no line breaks, so a path stays one piece to copy."""
    terminal.console.print(line, style=style, markup=False, highlight=False, soft_wrap=True)


def rows_table(counts: dict[str, dict[str, int]]) -> Table:
    """One line per table, one column of row counts per heading; '-' where the table does not exist."""
    table = Table("Table", box=None, pad_edge=False)

    for heading in counts:
        table.add_column(heading, justify="right")

    for name in sorted({name for rows in counts.values() for name in rows}):
        table.add_row(name, *(str(rows.get(name, "-")) for rows in counts.values()))

    return table


def print_state(state: DatabaseState) -> None:
    """Where the database is, its schema version against the code's, the pending steps, the rows, and what startup does."""
    stamps = ", ".join(str(stamp) for stamp in state.stamps) or "none"
    say(f"Database:        {state.backend.value} {state.location}")
    say(f"Schema version:  {stamps} (this code needs {state.required})")

    for step in state.pending:
        say(f"Pending step:    {step}")

    terminal.console.print(rows_table({"Rows": state.rows}))

    if state.refusal is not None:
        say(state.refusal, "red")
    elif not state.stamps:
        say(f"New: the next start creates every table at version {state.required}.")
    else:
        say("Current: startup opens it as it is.")


async def status(database: Database) -> int:
    print_state(await database.state())
    return 0


async def backup(database: Database) -> int:
    say(f"Backed up to {await database.backup()}")
    return 0


async def migrate(database: Database) -> int:
    """Nothing pending changes nothing; otherwise the backup, then each step and every table's rows before and after."""
    migration = await database.migrate()
    before, after = migration.before, migration.after

    if migration.backup is None and before.stamps:
        say(f"Already at version {after.required}. Nothing to migrate, and no backup was made.")
        return 0

    if migration.backup is None:
        say(f"The database is new: the next start creates every table at version {after.required}. Nothing to migrate.")
        return 0

    say(f"Backed up to {migration.backup}")
    say(f"Migrated from version {before.stamps[0]} to {after.stamps[0]}:")

    for step in before.pending:
        say(f"  {step}")

    terminal.console.print(rows_table({"Before": before.rows, "After": after.rows}))
    return 0


async def restore(database: Database, backup_path: Path, confirmed: bool) -> int:
    """Without --yes, says what a restore would replace and changes nothing."""
    if not confirmed:
        state = await database.state()
        say(
            f"`just db-restore` replaces the {state.backend.value} database at {state.location} with {backup_path}, after "
            "backing the current database up. Run it again with --yes to go ahead. Nothing changed."
        )
        return 1

    current = await database.restore(backup_path)
    first = f"Backed the current database up to {current}" if current else "The database had no table, so no backup was made"
    say(f"{first}, then restored {backup_path}:")
    print_state(await database.state())
    return 0


def parse(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="just db-<command>", description="The configured database's schema version and backups.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Where the database is, its schema version, the pending upgrade steps and the rows.")
    commands.add_parser("backup", help="Copies the database into backups/.")
    commands.add_parser("migrate", help="Backs the database up, then runs the pending upgrade steps in one transaction.")
    restore_command = commands.add_parser("restore", help="Backs the current database up, then puts a backup back.")
    restore_command.add_argument("backup", type=Path, help="A file that db-backup, db-migrate or db-restore wrote.")
    restore_command.add_argument("--yes", action="store_true", help="Replace the current database.")
    return parser.parse_args(arguments)


async def run(arguments: argparse.Namespace) -> int:
    async with open_database() as database:
        match arguments.command:
            case "status":
                return await status(database)
            case "backup":
                return await backup(database)
            case "migrate":
                return await migrate(database)
            case _:
                return await restore(database, arguments.backup, arguments.yes)


if __name__ == "__main__":
    command = parse(sys.argv[1:])
    exit_code = 1

    try:
        exit_code = asyncio.run(run(command))
    except (*STARTUP_REFUSALS, DatabaseCommandError) as error:
        say(str(error), "red")
    finally:
        # The database's aiosqlite worker thread outlives close() and would hold the interpreter at exit.
        os._exit(exit_code)
