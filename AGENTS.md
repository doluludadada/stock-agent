# stock-agent

Taiwan stock screening, watchlist and mock trading. The backend is in `backend/` and runs on
Python 3.14.7. Settings are in `config/appsetting.yaml`, and secrets are in `.env`.

This file is for every coding agent. Codex reads it directly, and `CLAUDE.md` imports it for
Claude Code.

## Rules

`docs/clean_architecture_guide.md` is the only rulebook. Read it before you change code under
`backend/src`. This file adds facts about this repository and changes no rule. When two rules
conflict, section 0 of the guide decides.

## Commands

Run these from `backend/`:

- Tests: `uv run pytest -q`
- Architecture check: `uv run python tools/architecture_check.py src --pyright`. It must end at `TOTAL 0`.
- Format and lint: `uv run ruff format` and `uv run ruff check`
- CLI: `PYTHONPATH=src uv run python -m d_presentation.cli.interactive`

## Before you finish

1. The tests pass and the architecture check ends at `TOTAL 0`.
2. Go through the judgment items of the guide's checklist against your diff. The check at 0 is
   not enough.
3. If a CLI menu or an API endpoint reaches the change, follow
   `.claude/skills/verify-stock-agent/SKILL.md`.
4. If the change touches orders, signals, trading rules, the Pipeline, `dependencies.py` or the
   trading settings, follow `.claude/skills/formal-verify-order-gate/SKILL.md`.
