set windows-shell := ["powershell", "-Command"]

active_venv:
    .venv\Scripts\Activate.ps1

dev-sync:
    uv sync --all-extras

format:
    cd backend; uv run ruff format

# Check backend/src against docs/clean_architecture_guide.md; add --pyright to count type errors too.
arch *args:
    cd backend; uv run python tools/architecture_check.py {{args}}

# Sets a new password for a user, on this machine, with its database and accounts key: for an administrator locked out.
[unix]
reset-password login:
    cd backend && PYTHONPATH=src uv run python -m d_presentation.cli.reset_password {{login}}

[windows]
reset-password login:
    cd backend; $env:PYTHONPATH="src"; uv run python -m d_presentation.cli.reset_password {{login}}

# Saves the official closes, material information, EPS statistics, valuation ratios, balance sheets, income statements,
# monthly revenue and TWSE news the TWSE and TPEX OpenAPI serve now into the archive, then prints every date, quarter
# and month it holds.
# The Web API does the same at its start and every api.archive_interval_hours (3 by default).
[unix]
archive-closes:
    cd backend && PYTHONPATH=src uv run python -m d_presentation.cli.archive_closes

[windows]
archive-closes:
    cd backend; $env:PYTHONPATH="src"; uv run python -m d_presentation.cli.archive_closes

# The database commands (docs/database-migrations.md). Each opens only the database that db.backend selects, so it also
# works on a database that startup refuses. Backups go to backups/ (owner-only); PostgreSQL's need pg_dump and pg_restore.

# The backend and where, the schema version and the code's, the pending upgrade steps, and each table's rows.
[unix]
db-status:
    cd backend && PYTHONPATH=src uv run python -m d_presentation.cli.database status

[windows]
db-status:
    cd backend; $env:PYTHONPATH="src"; uv run python -m d_presentation.cli.database status

# A consistent copy of the database in backups/, named after the UTC time and the schema version.
[unix]
db-backup:
    cd backend && PYTHONPATH=src uv run python -m d_presentation.cli.database backup

[windows]
db-backup:
    cd backend; $env:PYTHONPATH="src"; uv run python -m d_presentation.cli.database backup

# Backs the database up, then runs the pending upgrade steps in one transaction. Nothing pending changes nothing.
[unix]
db-migrate:
    cd backend && PYTHONPATH=src uv run python -m d_presentation.cli.database migrate

[windows]
db-migrate:
    cd backend; $env:PYTHONPATH="src"; uv run python -m d_presentation.cli.database migrate

# Backs the current database up, then puts a backup back: `just db-restore backups/<file> --yes`.
[unix]
db-restore backup *flags:
    cd backend && PYTHONPATH=src uv run python -m d_presentation.cli.database restore {{quote(join(invocation_directory(), backup))}} {{flags}}

[windows]
db-restore backup *flags:
    cd backend; $env:PYTHONPATH="src"; uv run python -m d_presentation.cli.database restore {{quote(join(invocation_directory_native(), backup))}} {{flags}}

ngrok:
    ngrok http 8800

# Backend Web API on the loopback address, one worker. Start it before the frontend (`just run-fn`), whose dev
# server proxies /v1 to http://127.0.0.1:8800. The first start creates secrets/accounts.key: back it up with the database.
alias run := run-bn

[unix]
run-bn:
    cd backend && PYTHONPATH=src uv run python main.py

[windows]
run-bn:
    cd backend; $env:PYTHONPATH="src"; uv run python main.py

build-docker:
    docker build -t chat-friend .

run-docker:
    docker run -p 8000:8000 --env-file .env chat-friend

[windows]
cli:
    @echo "Starting CLI..."
    cd backend; $env:PYTHONPATH="src"; uv run python -m d_presentation.cli.interactive

[unix]
cli:
    @echo "Starting CLI..."
    cd backend && PYTHONPATH=src uv run python -m d_presentation.cli.interactive

# Frontend (Stock Agent web UI). Requires Bun. Start the backend first with `just run-bn`.
alias run-fn := frontend-dev

[unix]
frontend-dev:
    cd frontend && bun install && bun run dev

[windows]
frontend-dev:
    cd frontend; bun install; bun run dev

[unix]
frontend-check:
    cd frontend && bun install --frozen-lockfile && bun run lint && bun run typecheck && bun run test && bun run build

[windows]
frontend-check:
    cd frontend; bun install --frozen-lockfile; if (-not $?) { exit 1 }; bun run lint; if (-not $?) { exit 1 }; bun run typecheck; if (-not $?) { exit 1 }; bun run test; if (-not $?) { exit 1 }; bun run build
