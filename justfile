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

ngrok:
    ngrok http 8800

# Backend Web API on the loopback address, one worker. Start it before the frontend (`just run-fn`), whose dev
# server proxies /v1 to http://127.0.0.1:8800. API_TOKEN and ADMIN_API_TOKEN come from .env.
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
