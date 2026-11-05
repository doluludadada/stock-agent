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

The first start creates `secrets/accounts.key`, the key of the saved usernames and emails: back up `secrets/` with the
database. The `ACCOUNTS_KEY` variable overrides the file, for Docker or production; `environment: prod` requires it
and never creates the file. The dev server
forwards same-origin `/v1` requests to `STOCK_AGENT_API_URL` (default `http://127.0.0.1:8800`) and adds nothing to
them: no credential and no CORS header. `HOST` and `PORT` move the backend. On the first start with no user, the
backend prints a one-time setup code on its console; the first-time setup in the web app needs it.

## Users and access

The server checks every request. Hiding a menu is never the protection.

| Access | Credential | Opens |
| --- | --- | --- |
| Public | none | `/v1/auth/status`, `/setup` (with the console's setup code), `/register`, `/sign-in`, `/sign-out`; `GET /v1/technical-settings/built-in-strategies`, `/v1/market/stocks?query`, `/v1/market/most-traded`, `/v1/market/breadth`, `/v1/market/stocks/{id}`, `/v1/market/indexes/{index}` |
| Signed in | the session cookie | `/v1/auth/me`, every other write, and the user's own runs, decisions, orders, watchlist, mock account, saved strategies, `/v1/market/stocks/{id}/technical`, valuation |
| Administrator | the session cookie of an administrator | `/v1/admin/users*` and `/v1/admin/settings*`, `/v1/admin/audit` |

- `POST /v1/auth/sign-in` (a username or an email, in any case, and the password) sets `stock_agent_session`:
  HttpOnly, SameSite=Strict, Path=/v1, Secure when the request came over https, for `accounts.session_days`. The
  server keeps only the token's SHA-256 and reads the session and its user on every request, so a deactivation or a
  new password signs the user out at the next request. `POST /v1/auth/sign-out` ends it.
- 401 means sign in (no session, an expired or ended one): the only answer that makes the app forget the user. 403
  means signed in but not allowed (not an administrator, registration closed, a user on a real-broker installation, a
  write without the app header) and never ends the session. 429 with Retry-After answers sign-in failures past
  `accounts.sign_in_failures_per_name` (per name and client address) or `sign_in_failures_per_client`, and
  registrations past `accounts.registrations_per_client`.
- Every write sends `X-Requested-With: stock-agent` (CSRF: another site cannot add the header without a preflight,
  which the API never grants) and, but for the `/v1/auth` steps, repeats `"confirm": true` in its body.
- Each user's data is their own: another user's run id answers 404. A user runs one workflow at a time, and users
  together run `accounts.max_concurrent_runs` at once (429 past it); an administrator's run always starts. A user's paid AI calls stop at `accounts.daily_ai_calls`
  a day and every user's together at `accounts.daily_ai_calls_total`; an administrator's count but are never refused.
- Behind a reverse proxy, the proxy must pass the visitor's address and scheme, or every visitor shares the proxy's
  address in the attempt limits and the cookie loses `Secure` under TLS: `proxy_set_header X-Forwarded-For
  $remote_addr; proxy_set_header X-Forwarded-Proto $scheme;` in nginx, and uvicorn's `--proxy-headers` with
  `FORWARDED_ALLOW_IPS` naming the proxy's address (127.0.0.1 by default; the proxy's bridge address in Docker).
  `frontend/docs/deployment.md` has the full setup. `Secure` follows the request's scheme rather than being always
  on, because the owner also signs in over plain http on the local network from a phone, where a `Secure` cookie
  would never come back.
- `/v1` answers only the host names in `api.allowed_hosts` (127.0.0.1 and localhost by default): a page on another
  site cannot reach it through DNS rebinding. The LINE webhook keeps its own signature check and is exempt from the
  session and the app header.
- Every `/v1` answer carries `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer` and `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`.
- A body over 2 MB, or a chunked body without a length, answers 413 before any route reads it.
- Messages from the server reach the browser through `public_text`: credentials, key-like query parameters and file
  system paths are replaced and long messages are cut. The full text stays in the server log.

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

`/v1/admin/settings*` edits every YAML file of `config/` (`appsetting.yaml`, `instructions.yaml`), each named only by
its `SettingsFile` id (`appsetting`, `instructions`), as a whole text, and the server runs on a saved file at once.
`tests/test_settings_refusal.py` fails when `config/*.yaml` and `SettingsFile` disagree. Every route needs a signed-in
administrator (`PrivateAccess` and `EditSystemSettings`: 401 signed out, 403 for a user, who stays signed in), and
every write the `X-Requested-With: stock-agent` header and `"confirm": true`.

### What a save does

1. The text is checked the way the app starts, by the one function a start and a reload use too (`startup_settings`):
   the settings load with the other file as it is on disk, the trading setup, the accounts key (prod refuses to start
   without `ACCOUNTS_KEY`) and the active AI provider's key. Every problem is located at its file, line and column.
   Refused: a key that names no setting, a key that names a value the environment owns (`password` under `db`,
   `OPENAI_API_KEY` under `ai`, the accounts key), YAML anchors and aliases (refused before anything expands them), a
   prompt outside `instructions.yaml`, a change of `environment`, which changes only when the app restarts, and a
   lockout of the editor: an
   `api.allowed_hosts` without the host the save was sent to, or an `api.settings_file_max_bytes` smaller than a
   settings file.
2. Every save and every restore needs the administrator's own password in the same request, so a stolen session alone
   changes no setting. Each try is counted before it is checked, under its own limit
   (`accounts.settings_password_failures` per administrator and address in `accounts.sign_in_window_minutes`), apart
   from the sign-in's.
3. The server opens the app on the new text: the whole startup, the database (a database older than the code is
   refused, `just db-migrate`) and the broker login included, within `api.settings_build_timeout_seconds` (30), and its
   database must hold an active administrator account of the one saving. A failure writes nothing.
4. The file is written byte for byte, after a backup of the old text (`.settings-admin/backups/<file>/`, owner-only,
   the latest `api.settings_backups_kept`), with an audit line naming the administrator by user id. The new settings
   are current from the next request on. A request or a run that started earlier finishes on the settings it started
   with; the earlier settings close when the last of them ends.

An edit made on disk outside the app is loaded the same way within `api.settings_poll_seconds` (2), or kept as a
refusal with its problems while the server keeps its settings; refused files are tried again once a file changes, or on
the administrator's reload request. The CLI loads the files again before it prints each menu, and once more after a
choice that may send an order (menus 2, 3 and 4): when they changed while the menu waited, it says so and prints the
menu again on them. Every setting a save or a reload puts in place applies at once, `behavior.log_level` and
`accounts.max_concurrent_runs` included (a run counts against the cap of the settings it starts on). HOST, PORT, `.env`
and the environment are not edited here. A revision covers the two YAML files only, so an edit of
`config/strategies/*.json` or `.env` alone reaches the running app at the next reload of a YAML file, or at a restart.

### API contract for the editor page

All bodies are JSON. `revision` is the SHA-256 the page read (64 hex characters).

| Request | Answer |
| --- | --- |
| `GET /v1/admin/settings` | `SettingsOverviewResponse` |
| `GET /v1/admin/settings/{file}` | `SettingsDocumentResponse` |
| `POST /v1/admin/settings/{file}/preview` `{revision, text}` | `SettingsEditResponse`, nothing written |
| `PUT /v1/admin/settings/{file}` `{confirm: true, revision, text, password}` | `SettingsEditResponse` with `saved` |
| `GET /v1/admin/settings/{file}/backups` | `[{backup_id, revision, created_at}]`, newest first |
| `POST /v1/admin/settings/{file}/backups/{backup_id}/preview` `{revision}` | `SettingsEditResponse` of the backup's text |
| `POST /v1/admin/settings/{file}/backups/{backup_id}/restore` `{confirm: true, revision, password}` | `SettingsEditResponse`, as a save |
| `POST /v1/admin/settings/reload` `{confirm: true}` | `SettingsOverviewResponse` after loading the files on disk again, refused ones included |
| `GET /v1/admin/audit?limit=1..200` | `[{recorded_at, file, action, actor, actor_name, from_revision, to_revision, settings}]`, newest first |

- `SettingsOverviewResponse`: `environment` (the one the server started in; show it read-only), `files` (each
  `{file, file_name, revision, running_revision, modified_at}`: a revision on disk that differs from the running one
  is an edit the server has not loaded), `refused` (`null`, or
  `{revisions, previous, problems, at}` for the last edit on disk the server would not start with, until a file
  changes again or a reload request applies it), and `draining` (earlier settings still finishing runs).
- The reload request is the administrator's explicit "Try again": it loads the files on disk now, refused ones that
  did not change included, because a refusal can come from outside the files (a database that was down, a broker
  login that failed). Its answer is the overview after it: `refused` is `null` and each `running_revision` equals
  `revision` when the reload applied; otherwise `refused` holds the new refusal. The watcher and the CLI never retry
  unchanged refused files on their own.
- `SettingsDocumentResponse`: `{status: <a files entry>, text}`, the whole text.
- `SettingsEditResponse`: `file`, `base_revision` (the revision on disk it was compared with), `revision` (the
  proposed text's; after a save, the file's), `running_revision`, `changed` (every setting path whose value differs,
  removed or added ones included; an empty list when the text does not parse, and `problems` then holds the parse
  problem), `diff` (unified diff lines), `problems`, `saved`, and `applied` (the server runs on this revision now).
- A problem is `{message, file, path, line, column}`; `file`, `path`, `line` and `column` may be `null` (a value from
  `.env`, the database or the broker). Lines and columns are 1-based: put the caret there. No message holds a value.
- Every error answer of the API is `{detail, code}`: `detail` in words for a person, `code` a stable `ErrorCode` the
  page switches on (one per refusal, from `ERROR_ANSWERS` in `web/app.py`; never switch on `detail`). The editor's:
  403 `password_required` (no password), 403 `password_refused` (a wrong one; the session stays), 403
  `administrators_only` (a signed-in user who is not an administrator; still signed in), 403 `settings_file_refused` (a
  symlinked, outside or too large file), 404 `settings_file_missing` (no such file or backup), 409 `settings_conflict`
  (the file or the running settings moved since the page read them: read again, keep the draft), 422
  `settings_refused` with `problems` too (the app would not start with it; nothing saved), 422 `settings_edit_refused`,
  422 `invalid_request` (a body that does not validate; `detail` is then FastAPI's list of fields), and 429
  `sign_in_throttled` with `Retry-After` (too many wrong passwords).

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
| Settings administration | Live: each settings file whole in a code editor that loads with the administrator's page only, checked by the server as it is typed with each problem at its line and column, saved with the administrator's password; the edits made on disk, the history and restore on the same page. Unsaved text survives a reload of that tab. |
| Hot reload | A Web save or restore applies at once; an edit made on disk applies within `api.settings_poll_seconds`, or is reported when the app would not start with it. |
| Accounts | Live: first-time setup with the console's code, sign-in by username or email, open registration, the account menu, and the administrator's users page (role, status, a new password). Each user has their own watchlist, mock account, runs and strategies. |

## Review findings (2026-11-03)

| # | Severity | Finding | Fix and regression test |
| --- | --- | --- | --- |
| 1 | P1 | Account history, runs, decisions, orders and the watchlist answered without a token. | Owner scope on every private read, now a signed-in session. `test_only_strategy_definitions_and_market_data_are_public`, `test_no_public_route_reaches_a_port_that_holds_a_users_data`. |
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

R1's allowlist is gone since the whole-file editor (2026-11-04): a restore puts the whole backup back through the same
checks, the password, and the same startup as a save (`tests/test_web_admin.py`).

`test.sh` (staged before this round) imports `c_infrastructure.system.config_loader`, which does not exist; it was
left as it is.

Checked without a finding: SQL goes through SQLAlchemy with bound parameters; no React `dangerouslySetInnerHTML`;
the production bundle has no source map, no `VITE_*` value and no secret; news,
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
- A settings save that answers 409 reloads the file, and the administrator's unsaved changes go with it; the message
  says to make the change again. The strategy designer keeps its draft instead.
- Settings saves and reloads are serialized by the runtime switch's lock inside one server process, and the revision is
  checked again just before the replace. A hand edit of the file in the instant between that check and the rename
  would be lost, and the directory is not synced after the replace, so a power cut right after a save can bring back
  the previous file (never a partial one); the next disk check then reloads what is there.
- A retired runtime's HTTP clients (PTT, Tavily, the news providers) are released by the garbage collector, not closed,
  when it closes; its database and its broker login are closed.
