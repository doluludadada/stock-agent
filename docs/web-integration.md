# Web integration

How the web UI in `frontend/` works with the backend Web API: how to start both, what each scope may do, how the
settings files are administered, which features use live data, what the review of 2026-11-03 found and fixed, and
how the change was measured and verified.

## Start it

From the repository root, in this order:

```bash
just run-bn   # backend on http://127.0.0.1:8800, one worker process
just run-fn   # frontend dev server on http://127.0.0.1:5173
```

Set two different long random strings in `.env` yourself: `API_TOKEN` (the owner) and `ADMIN_API_TOKEN` (the
administrator). The UI asks for them in an unlock dialog and keeps them in the tab's memory only, so a reload asks
again. The dev server forwards same-origin `/v1` requests to `STOCK_AGENT_API_URL` (default `http://127.0.0.1:8800`)
and adds nothing to them: no token and no CORS header. `HOST` and `PORT` move the backend.

## Scopes

The server checks every request. Hiding a menu is never the protection.

| Scope | Credential | Opens |
| --- | --- | --- |
| Public | none | `GET /v1/technical-settings/built-in-strategies`, `/v1/market/stocks?query`, `/v1/market/most-traded`, `/v1/market/breadth`, `/v1/market/stocks/{id}`, `/v1/market/indexes/{index}` |
| Owner | `Authorization: Bearer <API_TOKEN>` | every write, runs, decisions, orders, watchlist, account, saved strategies, `/v1/market/stocks/{id}/technical`, valuation |
| Administrator | `Authorization: Bearer <ADMIN_API_TOKEN>` | `/v1/admin/*` only |

- A scope whose token is unset answers 403 (fail closed). The administrator scope also answers 403 while
  `ADMIN_API_TOKEN` equals `API_TOKEN`; the owner token never opens it, and the administrator token never opens the
  owner's data.
- Every write repeats `"confirm": true` in its body.
- `/v1` answers only the host names in `api.allowed_hosts` (127.0.0.1 and localhost by default): a page on another
  site cannot reach it through DNS rebinding. The LINE webhook keeps its own signature check and is exempt.
- Bearer tokens are sent explicitly, never by the browser on its own, so a cross-site form or image cannot act with
  them (no CSRF). There is no CORS middleware, so another origin cannot read an answer.
- Every `/v1` answer carries `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer` and `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`.
- A body over 2 MB, or a chunked body without a length, answers 413 before any route reads it: FastAPI parses a body
  before it checks the bearer token.
- Messages from the server reach the browser through `public_text`: credentials, key-like query parameters and file
  system paths are replaced and long messages are cut. The full text stays in the server log.
- The UI drops a scope's cached data the moment its token changes or the server rejects it (401).

## Contract

`frontend/src/shared/api/openapi.json` is the API's OpenAPI document and `indicator-outputs.json` the outputs of each
indicator kind. `cd backend && uv run python tools/export_openapi.py` writes both; `tests/test_openapi_snapshot.py`
fails while either is out of date. `cd frontend && bun run api:types` generates `schema.gen.ts` from it, through
openapi-typescript in its own TypeScript 5 install (`frontend/tools/openapi`), because the app compiles with
TypeScript 7. The one transport (`shared/api/http.ts`) types every request and answer from that file; each feature owns
its endpoints, query keys and mapping.

The formula editor keeps a model of its own (an id per rule and condition, constants as tagged nodes) and converts in
one place, `features/strategies/api/mapping.ts`. Its test sends the three built-in strategies of `config/strategies`
(23, 23 and 20 rules: every effect, `ne`-free comparisons, constants, `latest_price`, arithmetic, bare comparisons and
every MACD output) through both directions and requires the backend's JSON back. `catalog.test.ts` compares every
indicator kind, parameter bound and output with the contract. A save carries the revision it read; a 409 keeps the
draft and offers to save it into the newer settings.

## Settings files

`/admin/settings` edits `config/appsetting.yaml` and `config/instructions.yaml`, named only by the `SettingsFile` id.

- Only `EditableSetting` paths change (AI model and behaviour, analysis windows, sentiment, collection rules, article
  quality, the missing-session and official-close limits, valuation, watchlist expiry, display limits, and the six
  prompts). The environment, broker, order mode, the score weights, buy and sell thresholds, sizing, stop-loss, and
  the history and quote freshness are `LockedSetting`: shown, never written. Credentials, database, folders and
  source URLs are neither.
- A proposal is the current file with the changes applied through ruamel's round-trip mode, which keeps comments and
  every other setting. It is validated by the same `load_settings` and `validate_trading_environment` that start the
  app, so placeholders of each prompt are checked too (`placeholders()` in `ai_config.py`). Problems name a location
  and a message, never a value: a settings error could otherwise echo a value from `.env`.
- Preview writes nothing. A save needs `confirm`, no problem and the revision (SHA-256 of the file) the page read; a
  stale one answers 409. It runs under a lock, copies the old text to `.settings-admin/backups/<file>/` (owner-only,
  the latest 20 kept), writes a temporary file next to the original with its permissions, flushes it to disk and
  renames it over, then appends a line to `.settings-admin/audit.jsonl` with the paths and revisions, never values.
  A symlinked file or one outside `config/` is refused.
- A restore puts a backup back through the same validation, revision check, backup and audit.
- Every setting applies at the next start: the running process keeps the configuration it loaded. The page shows the
  file's revision against the one the server runs on, and says when a restart is needed. There is no reload endpoint.

## Orders from the Web

Full Cycle, specific-stock analysis, valuation and market data never order. `POST /v1/runs/buzz-scan` and
`/v1/runs/intraday` start menus 2 and 3 only while `trading.execution_provider` is `mock` (`require_mock_broker`,
403 otherwise, whatever the order mode), through the same order gates and trading journal as the CLI. The Web has no
manual BUY. The order-gate check drives both routes with their real dependency and route function (menus `B` and
`I`) and adds `P8_WEB_MOCK_ONLY`; a mutant that removes the guard is caught.

One run at a time holds per server process only. A CLI on the same database can run beside it; on the mock broker
that can race the mock account's cash, which `formal-verify-order-gate` lists as not covered.

## Feature matrix

| Feature | Status |
| --- | --- |
| Strategy library and formula designer | Live: built-ins and catalog from the API, owner strategies saved with revisions, copy, delete, select for runs and Buzz. |
| Full Cycle and specific-stock runs | Live: start after confirming the AI cost, state polled until it ends, paged history, decisions, orders, reports saved with the run. |
| Buzz and Intraday runs | Live on the mock broker only; refused for any other broker. |
| Watchlist | Live: names, types and expiry; MANUAL add and remove with rollback on refusal. |
| Stock search and stock page | Live: listing search, cached daily bars, the active strategy's evaluation and indicator readings from the backend. No realtime quote on the Web. |
| Market overview | Live: the TAIEX daily trend over 1M to 1Y (Yahoo Finance `^TWII`, cached like a stock's history; any listed stock or ETF can replace it through `?target=`), the latest session's most traded stocks, and its breadth: advancers, decliners and unchanged stocks from the TWSE and TPEX listings' own change, and each industry's counts and average change, industries from the company profiles. Yahoo serves no TPEX index, so there is none. |
| Valuation | Live: market reference, specific stocks at a target P/E, undervalued scan with an explicit technical step, AI explanation per confirmed click. |
| Mock account | Live: positions, P&L, equity curve and as-of, labelled with the broker and order mode. |
| Settings administration | Live, as described above. |
| Raw YAML editing, hot reload, sign-in and multiple owners | Not supported. |

## Review findings (2026-11-03)

| # | Severity | Finding | Fix and regression test |
| --- | --- | --- | --- |
| 1 | P1 | Account history, runs, decisions, orders and the watchlist answered without a token. | Owner scope on every private read. `test_only_strategy_definitions_and_market_data_are_public`, `test_private_reads_are_refused_while_api_token_is_unset`. |
| 2 | P1 | `main.py` and `just run` bound 0.0.0.0 with reload on. | Loopback default, one worker, reload off; `just run-bn`. |
| 3 | P2 | No Host check, so DNS rebinding could reach the API. | `require_known_host`. `test_an_unknown_host_is_refused_before_any_route`. |
| 4 | P2 | FastAPI reads a body before the token check, and nothing bounded it. | 413 above 2 MB or chunked. `test_an_oversized_body_is_refused_before_any_route_reads_it`. |
| 5 | P2 | Run errors went to the browser verbatim (upstream URLs, paths). | `public_text`. `test_server_messages_reach_the_browser_without_credentials_or_paths`. |
| 6 | P2 | Stock id lists were unbounded and unchecked. | Pattern, at most 20, repeats dropped. `test_stock_id_lists_are_deduplicated_and_bounded`. |
| 7 | P2 | Specific-stock reports lived in memory and read as empty after a restart. | `run_stock_reports` table. `test_specific_stock_reports_survive_a_server_restart`. |
| 8 | P2 | The history cache never fetched bars older than it held, so a strategy needing more history failed on too few bars. | `ohlcv_windows` records the earliest session asked. `test_a_window_earlier_than_any_asked_before_is_fetched_once_and_a_short_history_is_not_asked_again`. |
| 9 | P2 | Dependency advisories. | `shadcn` (deepmerge, minimatch) is a devDependency; 17 Python packages upgraded (FastAPI 0.162, Starlette 1.10). Remaining below. |
| 10 | P3 | An inline script in `index.html` prevented a strict CSP. | `public/theme-init.js`; `vite preview` sends the production headers. |
| 11 | P3 | A broken prompt template failed only mid-run with a `KeyError`. | `placeholders()` checks each template at startup and before a save. |
| 12 | P2 | The first requests after a start could each seed the mock account, and the loser answered 500 on the unique key. | The seeding that loses rolls back and uses the seeded account. `test_two_first_reads_at_once_seed_the_account_once`. |
| 13 | P3 | A backup restore sent the page's latest revision instead of the one its preview was made from: once the page had read a newer file, the old preview's restore went through without a 409 and without showing the diff against that file. | A new preview drops the old one, a stale preview offers no restore, and a restore sends the previewed revision. The administration flow in `e2e/live.spec.ts` saves from elsewhere after a preview, expects the 409, and expects no restore button on the stale preview. |
| 14 | P3 | After a 409 the designer showed "save my draft again" before the newer settings arrived, so a quick click saved against the old revision and got another 409. | The banner appears once the newer settings are in. The 409 flow in `e2e/live.spec.ts` slows the settings read by 2 s and still saves. |

An independent review of the change found, and this round fixed:

| # | Severity | Finding | Fix and regression test |
| --- | --- | --- | --- |
| R1 | P1 | A backup restore wrote the backup's whole text, so it could put back locked settings (order mode, sizing, stop-loss) changed by hand since, and the audit named only the allowlisted ones. | A restore sets only the allowlisted values the backup holds on the current text. `test_a_restore_brings_back_only_allowlisted_values_and_keeps_locked_settings_changed_since`. |
| R2 | P2 | A save could pass validation and still stop the next start: an AI provider without its key, or a log level loguru does not know. | `AiConfig.missing_key()` in the save check; `log_level` is a loguru level. Two cases in `test_a_file_the_app_would_refuse_is_never_saved`. |
| R3 | P2 | `Transfer-Encoding: gzip, chunked` slipped past the body limit. | Any `Transfer-Encoding` answers 413. `test_a_body_without_a_plain_length_is_refused`. |
| R4 | P2 | A history backfill recorded its window for stocks the source skipped, so they were not asked again. | Windows only for stocks that came back. `test_a_window_is_recorded_only_for_stocks_the_source_answered`. |
| R5 | P2 | Two requests caching the same new stock at once could hit a unique-key error (`merge` selects, then inserts at commit). | The cache's writes run one at a time per process. Not reproduced in a test; across processes (CLI and server) the race remains. |
| R6 | P2 | `test_claude_refuses_to_start_without_its_key` read the machine's `.env`. | The test clears the key itself; the admin tests set the provider key they need. |
| R7 | P3 | After a 401 on a watchlist toggle the rollback put the private list back into the cache. | No rollback once the token is gone. |
| R8 | P3 | A change that would make a settings file too large answered 500. | It is a refused edit (422). |

`test.sh` (staged before this round) imports `c_infrastructure.system.config_loader`, which does not exist; it was
left as it is.

Checked without a finding: SQL goes through SQLAlchemy with bound parameters; no React `dangerouslySetInnerHTML`;
the production bundle has no source map, no `VITE_*` value and no token (only UI text naming `API_TOKEN`); news,
PTT, AI and YAML text is displayed as text and never executed; no endpoint takes a URL or a file path.

## Performance

Measured with `frontend/tools/measure-load.ts` (gzip-serving static server, headless Chromium, CPU slowed 4×,
median of 5 cold loads, the same machine and backend instance). The baseline build is kept in `.audit/baseline-dist`.

| Measure | Before | After |
| --- | --- | --- |
| Entry chunk (raw / gzip) | 769.7 KB / 246.4 KB | 450.7 KB / 140.1 KB |
| `/` script on the wire | 409.3 KB | 396.1 KB |
| `/` largest contentful paint | 1380 ms | 780 ms |
| `/` main-thread long tasks | 5, 962 ms | 3, 434 ms |
| `/stocks/2330` script on the wire | 371.1 KB | 354.4 KB |
| `/stocks/2330` largest contentful paint | 1324 ms | 1140 ms |
| `/stocks/2330` long tasks | 7, 1075 ms | 4, 776 ms |

The gain comes from removing the demo market generator from the app shell (the search no longer computes every demo
stock's bars and indicators), loading data per route, and `"sideEffects"` in `package.json`, which stopped the strategies
barrel from pulling the designer and Motion into the overview. The script on the wire barely moved: both builds still
loaded the chart chunk on every page, because that chunk had also captured React, which recharts shares with the app
shell. A later fix gives the shell's packages their own `react` and `vendor` chunks (Rolldown `codeSplitting` groups
tagged `$initial`, ahead of the `charts` group), so only the stock page downloads recharts:

| Measure, without a backend (bytes do not depend on timing) | Before the chunk fix | After |
| --- | --- | --- |
| `/` script on the wire | 399.0 KB | 285.6 KB |
| `/` requests | 21 | 21 |
| `/stocks/2330` script on the wire | 357.3 KB | 356.6 KB |
| Chunks every page loads (gzip) | entry 133.4 KB, charts 116.5 KB, shared 78.9 KB, 10.7 KB | entry 10.3 KB, react 99.1 KB, vendor 86.3 KB, shared 30.4 KB |

The overview's saving matches the chart chunk (112.4 KB gzip). Timing was not measured again after this fix: other
CPU-bound jobs held the machine at a load average near 400, which makes paint and long-task numbers meaningless. The
tool now exits 1 when a load logs an error or renders no `main` landmark, and every page of the new build loaded
without one. The build uses `codeSplitting` instead of the deprecated `advancedChunks`, and no chunk passes the
default 500 KB warning. Numbers compare builds on this machine only. Search is debounced (250 ms) and a newer query
aborts the older request; polling runs only while a run runs, stops at its end and in a background tab.

The overview later got its trend chart back. The chart loads lazily after the route, so the cards and skeletons do not
wait for recharts. Measured once each with the real API: `/` now makes 25 requests and moves 399.3 KB of script, the
same script as the round-2 build, which loaded recharts without showing a chart (20 requests, 399.0 KB). The 46 KB
more in total is mostly the year of 0050 daily bars.

## Verification

- Backend: full `pytest` (1033 passed), `architecture_check.py src --pyright` at `TOTAL 0`, Ruff format and check.
- Frontend: `bun run lint` (oxlint and boundaries), `tsc -b`, 35 Vitest tests, production build.
- `e2e/live.spec.ts` drives the real app against a real backend in a disposable verify-stock-agent instance whose
  key for the active AI model is a placeholder, so every AI call answers 401: the strategy round trip, a 409 resolved
  by saving into newer settings while the settings read is slowed, search, stock page and watchlist, a specific-stock
  run, the account, administration with preview, save, backup, a refused stale restore and a restore, overflow at
  desktop and mobile, English and light theme, keyboard focus, and a running badge that stops spinning under reduced
  motion. Every assertion about saved data reads the server. All 10 pass against the dev server and against the
  production build served by `vite preview` with the production headers. The three regression flows (409, stale
  restore, reduced motion) were each run once with their fix removed and failed at the step that checks it.
- Order gate: on the final code, menus 1 2 3 4 7 and the Web routes B and I pass P1 to P8 in 744,678 runs. The P8
  mutant (the Web API starting Buzz on any broker) is caught. The other mutants and the `--stocks 2` profile did not
  finish in this round: other CPU-bound jobs held the machine at a load average of 400 to 540.

## Residual risks

- `bun audit` still lists deepmerge (low, no fixed release) and minimatch (moderate) under the `shadcn` CLI, a
  development tool that never reaches the browser or the production install (`bun audit --prod` finds nothing).
- pip-audit still lists chromadb (no fixed release), curl-cffi (pinned by yfinance), filelock (fix needs a major) and
  urllib3 (pinned by kubernetes, reached through chromadb and the Google SDK, not by the app's own HTTP, which uses
  httpx).
- `GET /v1/market/stocks/{id}` and `/v1/market/indexes/{index}` are public and fetch an uncached history from Yahoo at
  most once per retry interval; put a rate limit in the reverse proxy before exposing them.
- Tokens are not accounts: one owner, one administrator. A reload asks for the token again by design.
- A settings save that answers 409 reloads the file, and the administrator's unsaved changes go with it; the message
  says to make the change again. The strategy designer keeps its draft instead.
- Settings writes are serialized inside one server process, and the revision is checked again under that lock just
  before the replace. A hand edit of the file in the instant between that check and the replace would be lost, and the
  directory is not synced after the replace, so a power cut right after a save can bring back the previous file (never
  a partial one).
