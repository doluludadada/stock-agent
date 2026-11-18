# syntax=docker/dockerfile:1
# The Web API and the project's commands. compose.yml builds and runs it. It publishes no port and keeps its files in
# /state.

FROM python:3.14.7-slim-trixie AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

FROM python:3.14.7-slim-trixie

# pg_dump and pg_restore of the major version of the postgres service in compose.yml, for the database commands
# (docs/database-migrations.md). Debian's own client is older, so this one comes from the PostgreSQL project's repository.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates postgresql-common \
    && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY src /app/src
COPY main.py /app/main.py

# STOCK_AGENT_ROOT is the project root: the app reads config/ from it and saves everything under it (get_project_root).
# The working directory is the same folder, because Shioaji's log resolves its path against it. HOME is writable for
# whichever user compose.yml runs the container as. ONNX Runtime, which the article store's embedding model imports,
# and the Hugging Face client that fetches that model once into /state/embedding_models, each
# upload usage telemetry unless told not to before they are imported; the site reports nothing about itself.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    STOCK_AGENT_ROOT=/state \
    HOME=/tmp \
    ORT_DISABLE_TELEMETRY=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HOST=0.0.0.0
WORKDIR /state
# A name for user 1000, the default of APP_UID in compose.yml: SinoPac's SDK looks its user up by name at each login.
RUN useradd --uid 1000 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin stock-agent
USER 1000:1000
EXPOSE 8800

# main.py starts uvicorn with one worker.
CMD ["python", "/app/main.py"]
