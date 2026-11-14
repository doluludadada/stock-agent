"""
The copies of the whole database that `just db-backup`, `db-migrate` and `db-restore` make and put back with
PostgreSQL's pg_dump and pg_restore. They copy every table as it is and never read a domain model.
"""

import asyncio
import os
import shutil

from b_application.config.app_config import DbConfig


class DatabaseCommandError(RuntimeError):
    """
    A database command that stopped: pg_dump or pg_restore failed or is missing, a file to restore is not a backup, or
    an upgrade failed after its backup and rolled back. The message says what the database holds now. Only the database
    commands raise it, and they print it alone.
    """


async def run_postgresql_client(program: str, db: DbConfig, *arguments: str) -> None:
    """
    Runs pg_dump or pg_restore against the database `db` names, its password in PGPASSWORD, never on the command line.
    Says how to install the program when it is not on PATH, and gives the program's own message when it fails.
    """
    executable = shutil.which(program)

    if executable is None:
        raise DatabaseCommandError(
            f"{program} is not on PATH. Install PostgreSQL's client programs, of the server's major version or newer: "
            "on macOS `brew install libpq`, then add $(brew --prefix libpq)/bin to PATH; on Debian or Ubuntu "
            "`sudo apt install postgresql-client`; on Windows the Command Line Tools of the PostgreSQL installer. "
            "Nothing changed."
        )

    target = (f"--host={db.host}", f"--port={db.port}", f"--username={db.user}", f"--dbname={db.name}", "--no-password")
    process = await asyncio.create_subprocess_exec(
        executable,
        *target,
        *arguments,
        env={**os.environ, "PGPASSWORD": db.password},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    messages = (await process.communicate())[1].decode(errors="replace").strip()

    if process.returncode != 0:
        raise DatabaseCommandError(f"{program} failed with exit status {process.returncode}: {messages}")
