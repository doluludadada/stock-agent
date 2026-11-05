# Database migrations

The SQL database, SQLite's `stock_agent.db` or PostgreSQL, holds one row in the table `schema_version`: the schema
version of the code that created or last upgraded it. The code's own version is `SCHEMA_VERSION` in
`backend/src/c_infrastructure/database/models/schema_version_dto.py`. Startup creates a new database at that version,
opens a database of that version, and refuses every other one without changing it. Upgrading a database of an older
version is a command you run on purpose, `just db-migrate`, and it backs the database up first.

## Upgrade the database after you update the code

When the code needs a newer version than the database holds, the CLI and the Web API stop at startup with this message:

```text
The database is at schema version 1, and this version of stock-agent needs 3. Startup never upgrades a database.
Remedy: run `just db-migrate`. It backs the database up into backups/ first, then upgrades it in one transaction. `just db-status` shows the steps it runs.
```

1. Stop the CLI and the Web API.
2. Run `just db-status`. It prints where the database is, its schema version and the code's, the upgrade steps that are
   pending, and the row count of every table.
3. Run `just db-migrate`. It writes a backup into `backups/`, runs the pending steps in one transaction, and prints the
   row count of every table before and after.
4. Start the app again.

If a step fails, the transaction rolls back. The database keeps its version and every row, and the message names the
step that failed and the backup. A second `just db-migrate` prints `Already at version 3. Nothing to migrate, and no
backup was made.` and changes nothing.

## Restore a backup

1. Stop the CLI and the Web API.
2. Run `just db-restore backups/<file> --yes`.

Without `--yes`, the command prints what it would replace and changes nothing. With `--yes`, it first backs up the
current database, unless the database has no table, and then puts the backup back:

- On SQLite, it copies the backup into `stock_agent.db` through SQLite's backup API.
- On PostgreSQL, it runs `pg_restore --clean --if-exists --single-transaction --no-owner` into the configured database.
  `pg_restore` drops and recreates only the tables the backup holds, so a table created after the backup stays.

The command never deletes or changes the backup it restores from. Startup refuses a restored database of an older
version like any other. Run `just db-migrate`, or run the version of stock-agent that wrote it.

## Write an upgrade step

A change to an existing table needs an upgrade step: a new, renamed, retyped or dropped column, a new primary key or
unique constraint, or a change to how a column stores its value. A new table needs no step, because startup creates it.

1. Write an `async` function in `schema_version_dto.py` that takes only the `AsyncConnection`. Name each table and
   column as it was at the version the step starts from, with `text()`, or `table()` and `column()`. Never use
   today's SQLModel classes, which describe the newest version. When SQLite and PostgreSQL need different statements,
   keep one list per backend, as `OWNER_STEP` does.
2. Append the function to `UPGRADES`. `SCHEMA_VERSION` is `len(UPGRADES) + 1`, so it rises by one.
3. Run `cd backend && uv run python tools/schema_snapshot.py`. It writes `tests/fixtures/schema/version_<N>.json` for
   the new version.
4. Test the step on both backends. Build a database of the previous version from the tables that version created, fill
   it with rows, run `DatabaseConnector.migrate()`, and check every row. Also check that a failure inside the step
   leaves the database as it was. `tests/test_schema_upgrade.py` does both for the step from version 2 to 3.

Each step follows these rules:

- Never commit inside a step. `upgrade()` stamps the new version before the first step runs, so SQLite's driver has
  opened the transaction before any `ALTER TABLE`, and a later failure rolls everything back.
- SQLite cannot change a primary key in place. Create the new table, copy the rows into it, drop the old table, and
  rename the new one. `give_rows_their_owner` does this for `watchlists`.
- On PostgreSQL, a column that stores an enum has a named `ENUM` type, so a new member needs
  `ALTER TYPE <name> ADD VALUE '<member>'`. A value added in a transaction is usable only after the transaction commits,
  so the step must not write rows with it.

`tests/test_schema_snapshot.py` stops a change to an existing table that has no step. It compares the SQLModel classes
with `tests/fixtures/schema/version_<SCHEMA_VERSION>.json`, which records each table's columns, their types and
nullability, the primary key, the unique constraints and the foreign keys. A changed or removed table fails with `a
change to an existing table needs an upgrade step: append one to UPGRADES, then regenerate the snapshot`. An added
table passes that test, and a second test asks you to regenerate the snapshot. `tools/schema_snapshot.py` refuses to
rewrite the snapshot of the current version while an existing table differs from it.

## The commands

Each command opens only the database that `db.backend` selects. It needs no accounts key, no AI key and no broker,
and it works on a database that startup refuses.

| Command | What it does | Exit status |
| --- | --- | --- |
| `just db-status` | Prints the backend and where the database is, its schema version and the code's, the pending upgrade steps, the row count of every table, and what startup does with the database. It changes nothing, and it does not create a missing SQLite file. | 0 |
| `just db-backup` | Writes a backup into `backups/` and prints its path. | 0, or 1 when the backup failed |
| `just db-migrate` | With no step pending, prints `Already at version N` and changes nothing. Otherwise writes a backup, runs the pending steps and checks every table against the code in one transaction, then prints each step and every table's row count before and after. | 0 when the database is new or ends at the code's version, 1 when it was refused or the upgrade rolled back |
| `just db-restore <backup> --yes` | Backs up the current database, then replaces it with `<backup>`. | 0, or 1 without `--yes` or when refused |

A path given to `just db-restore` is relative to the folder you run `just` from.

## Backups

- `backups/` is at the project root, is created with mode 700, and is ignored by git. Each backup file has mode 600.
- A SQLite backup is `backups/stock_agent.<yyyymmdd-HHMMSS>.v<N>.db`, a copy made through SQLite's backup API, which
  is consistent while the app reads or writes the file.
- A PostgreSQL backup is `backups/<DB_NAME>.<yyyymmdd-HHMMSS>.v<N>.dump`, written by `pg_dump --format=custom`.
- The time is UTC, and `<N>` is the schema version of the database, `none` when it has no stamp. A second backup in the
  same second gets `-2` after the time.
- A backup holds the whole database: the hashed passwords, the sealed usernames and emails, and every trading record.
  Keep backups private, and keep a backup of `secrets/accounts.key` with them, or of the `ACCOUNTS_KEY` variable when
  you set one, because only the original key reads the saved users.

## SQLite and PostgreSQL

- On PostgreSQL the commands read `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` and `DB_NAME`, as the app does. They
  pass the password to `pg_dump` and `pg_restore` in `PGPASSWORD`, never on the command line, and never print it.
- `pg_dump` and `pg_restore` must be on `PATH`, of the server's major version or newer. Without them, the commands say
  how to install them and change nothing. On macOS, run `brew install libpq` and add `$(brew --prefix libpq)/bin` to
  `PATH`. On Debian or Ubuntu, run `sudo apt install postgresql-client`. On Windows, install the Command Line Tools of
  the PostgreSQL installer.
- PostgreSQL runs DDL inside a transaction. SQLite does too, once the transaction has begun, which is why `upgrade()`
  writes the stamp first.
- SQLModel stores an enum as a `VARCHAR` on SQLite and as a named `ENUM` type on PostgreSQL. A new enum member needs a
  step only on PostgreSQL. The snapshot records each enum's members, so it asks for the step on both.
