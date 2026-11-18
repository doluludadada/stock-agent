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
database. The `ACCOUNTS_KEY` variable overrides the file; `environment: prod` requires it
and never creates the file. The dev server
forwards same-origin `/v1` requests to `STOCK_AGENT_API_URL` (default `http://127.0.0.1:8800`) and adds nothing to
them: no credential and no CORS header. `HOST` and `PORT` move the backend. On the first start with no user, the
backend prints a one-time setup code on its console; the first-time setup in the web app needs it.

## Users and access

The server checks every request. Hiding a menu is never the protection.

| Access | Credential | Opens |
| --- | --- | --- |
| Public | none | `/v1/auth/status`, `/setup` (with the console's setup code), `/register`, `/sign-in`, `/sign-out`, `/google/start`, `/google/callback`; `GET /v1/technical-settings/built-in-strategies`, `/v1/market/stocks?query`, `/v1/market/most-traded`, `/v1/market/breadth`, `/v1/market/stocks/{id}`, `/v1/market/indexes/{index}` |
| Signed in | the session cookie | `/v1/auth/me`, every other write, and the user's own runs, decisions, orders, watchlist, mock account, saved strategies, `/v1/market/stocks/{id}/technical`, `/v1/market/quotes`, valuation |
| Administrator | the session cookie of an administrator | `/v1/admin/users*` and `/v1/admin/settings` |

- Each feature of the site has a visibility under `features` in `config/appsetting.yaml`: `off`, `administrators`
  or `everyone` (every signed-in user; a route that needs no sign-in stays open to a visitor). `Feature` in
  `a_domain/types/enums.py` is the one list. A route names its feature with `shows(Feature.X)` (`web/session.py`) and
  answers 403 `feature_hidden` to a viewer who may not see it, after the sign-in check and before everything else.
  `tests/test_feature_visibility.py` fails when a feature gates no route. `GET /v1/auth/status` answers every
  feature's visibility in `features`, and the web app shows a page when it is `everyone`, or `administrators` and the
  user has the permission `see_administrator_features`. A save in the settings page applies at once.

  | Feature | Routes it gates | Shipped |
  | --- | --- | --- |
  | `market_overview` | `/v1/market/most-traded`, `/breadth` | everyone |
  | `ranking` | `/v1/rankings/*` | everyone |
  | `stock_pages` | `/v1/market/stocks/{id}/financials`, `/analysis`, `/news`, `/technical`, and `/ranking`, the stock's score, which needs `ranking` shown to the viewer too | everyone |
  | `watchlist` | `/v1/watchlist/*` | everyone |
  | any one of `holdings`, `mock_account`, `ranking`, `stock_pages`, `watchlist` | `/v1/market/quotes`, the realtime quotes those pages show | as each of them |
  | `market_overview` | `/v1/market/index-quotes`, the index's realtime quote on the home page and the market overview | everyone |
  | `valuation` | `/v1/valuation/*` | administrators |
  | `full_cycle`, `specific_stock`, `buzz`, `intraday` | each one's start under `/v1/runs`; `specific_stock` also the manual BUY. A run's own pages (`GET /v1/runs*`) need any one of the four | administrators |
  | `strategy_library`, `strategy_designer` | `PUT /v1/technical-settings` (either one) | administrators |
  | `strategy_backtest` | `/v1/backtests/*` | administrators |
  | `mock_account` | `/v1/account/history`, `/trades` and every order route with `broker=mock`, `/v1/account/reset`, `POST /v1/runs/{id}/follow`, `/v1/rankings/follow` (with `ranking`); the mock account's holdings in `/v1/holdings` | administrators |
  | `sinopac_account` | `/v1/account/brokerage`, and `/v1/account/history` and `/trades` with `broker=shioaji`; the SinoPac account's holdings in `/v1/holdings`. Reading only, and only for a user with `use_real_broker` | administrators |
  | `sinopac_ordering` | every order route with `broker=shioaji`, and SinoPac in `/v1/account/brokers`. Off, no order reaches SinoPac: `BrokerAccessRule` refuses it at the send too | off |
  | `holdings` | `/v1/holdings/*` | everyone |
  | `world` | `/v1/world`. Off, the site also reads no world feed and writes no world brief | everyone |

  The listing search, a stock's bars, the index trend, `GET /v1/technical-settings` and the audience are read by
  several features and stay ungated. A visibility is one more gate and never replaces one: SinoPac shown to everyone
  still answers a user 403 `real_broker_refused`, and every order gate still checks each order. The CLI has no such
  gate: only an administrator signs in to it.
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
- The server replays `accounts.max_concurrent_backtests` strategy backtests and ranking backtests at once, every
  user's together, and one more waits its turn. A user's request past `accounts.max_backtests_per_user` replaying or
  waiting answers 429 `too_many_backtests`.
- Registration ships closed (`accounts.registration_open: false`), and `shioaji.server: production` refuses it
  open. The API docs (`/docs`, `/redoc`, `/openapi.json`) are served only in `environment: dev`.
- Behind a reverse proxy, the proxy must pass the visitor's address and scheme, or every visitor shares the proxy's
  address in the attempt limits and the cookie loses `Secure` under TLS: `proxy_set_header X-Forwarded-For
  $remote_addr; proxy_set_header X-Forwarded-Proto $scheme;` in nginx, and uvicorn's `--proxy-headers` with
  `FORWARDED_ALLOW_IPS` naming the proxy's address (127.0.0.1 by default; `compose.yml` sets it to its own network).
  `frontend/docs/deployment.md` has the full setup, and the Docker Compose deployment. `Secure` follows the request's scheme rather than being always
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

## Sign in with Google

A site that has a Google OAuth client signs users in with Google next to the password sign-in. The browser goes to
`GET /v1/auth/google/start`, signs in at Google, and comes back to `GET /v1/auth/google/callback`. The callback sets the
same session cookie as `POST /v1/auth/sign-in` and sends the browser to the app. The page loads no script from Google,
so the Content-Security-Policy of the app stays as it is.

### Set up sign-in with Google

Google accepts a redirect URI only over https, at a host name under a public suffix. A Tailscale name such as
`my-server.my-tailnet.ts.net`, served by `tailscale serve`, meets both rules. An IP address does not. The one exception
is `http://localhost`, for development.

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and create a project, or select one.
2. Open **Google Auth Platform**. On **Branding**, enter an app name and your email. On **Audience**, select the user
   type **External**, keep the publishing status **Testing**, and add your Gmail address under **Test users**. In
   testing mode, only the test users can sign in.
3. On **Clients**, create a client of the application type **Web application**. Under **Authorized redirect URIs**, add
   exactly `https://<host name of the site>/v1/auth/google/callback`. Leave **Authorized JavaScript origins** empty.
4. Copy the client ID and the client secret into `.env`:

   ```bash
   GOOGLE_CLIENT_ID="<client ID>"
   GOOGLE_CLIENT_SECRET="<client secret>"
   ```

5. In `config/appsetting.yaml`, set the address of the site and your email, and check that `api.allowed_hosts` names
   the host:

   ```yaml
   api:
     allowed_hosts: ["127.0.0.1", "localhost", "<host name of the site>"]
   accounts:
     public_origin: "https://<host name of the site>"
     google_administrator_emails: ["<your Gmail address>"]
   ```

6. Restart the server. `GET /v1/auth/status` now answers `"google_sign_in": true`, and the sign-in page and the
   first-time setup page show **Sign in with Google**.

The server builds the redirect URI from `accounts.public_origin`, never from the request's Host header. Startup refuses
a setup that is not whole or not safe, and the message names what to change: one or two of the three values without the
others, a public origin that is not https (only `http://localhost` and `http://127.0.0.1` may be http), a public
origin whose host `api.allowed_hosts` leaves out, and a Google address that is not https.

### Who may sign in

The server reads the email from Google's ID token and uses it only when Google says that the email is verified. It
compares the whole email, in any case. No setting takes a domain or a wildcard.

| The email | Result |
| --- | --- |
| In `accounts.google_administrator_emails` | Signs in as an administrator. The first sign-in creates the account. On an installation with no user, the account takes the place of the first-time setup, and the setup code still works for anyone else. An account that has the email is used, and a user is made an administrator. |
| In `accounts.google_allowed_emails` | Signs in as a user, whether registration is open or not. The first sign-in creates the account. |
| On neither list | Signs in as a user only while `accounts.registration_open` is true. Otherwise the browser returns to the sign-in page with a refusal, and no account is created. |
| Of a deactivated account | Refused, whatever list names the email. |

An installation with no user accepts only an administrator email, so the first account is always an administrator.

An account that a sign-in with Google creates has no password: `GET /v1/auth/me` answers `"has_password": false`. Its
username is the part of the email before the `@`.

The app never verified the email of an account that someone registered with a password. A sign-in with Google
therefore removes the password and ends the sessions of the account it finds, unless that account is already an
administrator. Without this rule, a person who registered your address before you could keep a password to your
account.

### Use the CLI or a password with a Google account

The CLI and `POST /v1/auth/sign-in` need a password. To give a Google account one, run `just reset-password <username
or email>` on the server. The account then signs in both ways. An administrator can also set a password for another
user on the users page, but the next sign-in with Google of a user who is not an administrator removes it again.

### How the flow is protected

- The start makes a random `state`, a random `nonce` and a PKCE verifier, and sends Google the S256 challenge. The three
  values travel in the cookie `stock_agent_google_flow`: HttpOnly, SameSite=Lax, Path=/v1/auth/google, for
  `accounts.google_flow_minutes`. The cookie is Lax because Google's redirect back is a navigation from another site,
  which never carries a Strict cookie. The callback clears it, so a return from Google works once.
- The callback refuses a `state` that is not the cookie's, exchanges the code at Google's token endpoint with the
  client secret and the verifier, and checks the ID token: the issuer, this client as the only audience, the expiry,
  the `nonce`, and `email_verified`.
- The server does not check the signature of the ID token against Google's keys. The token comes straight from Google's
  token endpoint over TLS, on a request that the client secret authenticates, and OpenID Connect Core 3.1.3.7 allows
  TLS server validation in place of the signature check for this flow. The token never leaves the server. The settings
  refuse a token endpoint that is not https. This choice needs no JWT library and no cache of Google's keys.
- The session cookie keeps its flags: HttpOnly, SameSite=Strict, Path=/v1. A browser stores a Strict cookie that a
  response to a cross-site navigation sets. The app then reads `/v1/auth/me` with a request of its own, which is
  same-site and carries the cookie. `frontend/e2e/google.spec.ts` proves this in a browser, with Google's stand-in
  on another site than the app.
- Every start and every return from Google counts toward `accounts.sign_in_failures_per_client` per client address in
  `accounts.sign_in_window_minutes`. A return that proves a Google identity takes itself and its start back. Past the
  limit, the browser returns to the app with `?google=throttled`.
- The log names why a sign-in was refused and the client address. It holds no code, token, `state`, client secret or
  email, and the access log writes the two Google endpoints without their query.

### Confirm a settings save without a password

A save of the settings needs the administrator's password again, so a stolen session alone changes no setting. An
administrator without a password confirms each save with a fresh sign-in to Google instead:

1. The app makes a random id for the save, keeps the changes in the tab's session storage, and sends the browser to
   `GET /v1/auth/google/start?confirmation=<id>`.
2. The server asks Google for `max_age=0` and for the `auth_time` claim.
3. The callback accepts the ID token only when `auth_time` is at most `accounts.google_fresh_authentication_seconds`
   old and the email is an active administrator's. It then grants that administrator the id, for the same number of
   seconds, and returns the browser to the settings form.
4. The app sends the save with `"google_confirmation": "<id>"`. The grant is used up, whether the save succeeds or not.

A Google session that was left open confirms nothing, and a grant confirms one save by one administrator. Without a
grant, the save answers 403 `google_confirmation_required`. An administrator who has a password confirms with the
password only. A save that would leave an administrator without a password no way to sign in is refused: it must keep
Google set up and the administrator's email on the list.

Google's documentation does not list `max_age`, and says that the token carries `auth_time` when the request asks for
it and the client's settings enable it. If Google returns no `auth_time`, or an old one, the server refuses the
confirmation and the settings form says so. Sign out of Google and sign in again, then save, or set a password with
`just reset-password`. The round trip with the real Google is not proven yet: the tests and the browser run use the
stand-in `backend/tests/support/fake_google.py`.

## Contract

`frontend/src/shared/api/openapi.json` is the API's OpenAPI document and `indicator-outputs.json` the outputs of each
indicator kind. `cd backend && PYTHONPATH=src uv run python tools/export_openapi.py` writes both, and
`settings-fields.json`, the settings form's paths with each one's control, group, options and unit; `tests/test_openapi_snapshot.py` fails while any of the
three is out of date. `cd frontend && bun run api:types` generates `schema.gen.ts` from it, through
openapi-typescript in its own TypeScript 5 install (`frontend/tools/openapi`), because the app compiles with
TypeScript 7. The one transport (`shared/api/http.ts`) types every request and answer from that file; each feature owns
its endpoints, query keys and mapping.

The formula editor keeps a model of its own (an id per rule and condition, constants as tagged nodes) and converts in
one place, `features/strategies/api/mapping.ts`. Its test sends the built-in strategy of `config/strategies`
(23 rules: every effect, `ne`-free comparisons, constants, `latest_price`, arithmetic, bare comparisons and
every MACD output) through both directions and requires the backend's JSON back. `catalog.test.ts` compares every
indicator kind, parameter bound and output with the contract. A save carries the revision it read; a 409 keeps the
draft and offers to save it into the newer settings.

## Settings files

`/v1/admin/settings` is the system settings as a form: the settings of `config/appsetting.yaml` an administrator
changes and the AI prompts of `config/instructions.yaml`, and no YAML. The settings only an operator changes, in the
file, are not on it. `tests/test_settings_refusal.py` fails when `config/*.yaml` and `SettingsFile`
disagree. Both routes need a signed-in administrator (`PrivateAccess` and `EditSystemSettings`: 401 signed out, 403 for
a user, who stays signed in), and the save the `X-Requested-With: stock-agent` header and `"confirm": true`.

| Request | Answer |
| --- | --- |
| `GET /v1/admin/settings` | `[SettingField]`, in the settings classes' order |
| `PUT /v1/admin/settings` `{confirm: true, changes: [{path, value}], password}` | `[SettingField]` after the save |

- A `SettingField` is `{path, kind, group, value, options, steps, minimum, maximum, step, unit, nullable,
  restart_only}`. `path` is the setting's dotted path (`ai.temperature`; a prompt by its settings path,
  `ai.system_prompt`). `kind` (`SettingKind`) picks the control, and all but the last three are chosen, never typed:
  `switch`, `choice` (one of `options`), `choices` (several of `options`), `steps` (a number picked from `steps`),
  `range` (a number moved from `minimum` to `maximum` by `step`), `date`, `time`, and the typed `text`, `lines` (a
  list of plain values) and `structure` (a map or a nested list, edited as JSON). `unit` (`SettingUnit`) says what a
  number counts, and `nullable` that the setting may be unset. `group` (`SettingGroup`) is where the page shows it:
  `site_access`, `features`, `ranking`, `data_history`, `ai`, `trading_limits` or `advanced`, which holds every typed
  setting. `value` is what the file sets, as JSON, or the setting's default when
  the file leaves it out; a value that is none of the options or steps still shows and stays until the administrator
  picks another. `restart_only` marks `environment` and `audience`, which a save never changes.
- A settings class says what the form cannot read from the type, in the field's `json_schema_extra`: `steps` (the
  numbers that make sense), `step`, `unit`, `options` (choices the settings do not enforce, such as the benchmark's
  ETFs), `strategy` (the built-in strategies on disk are the options) and `group` (on a section in `AppConfig`, or
  on one field). `operator_only`, on a section or on one field, keeps a setting off the form: the addresses and
  patterns of the data sources, the database, the folders, the exchange's hours and tick tables, the strategy
  search's tuning, the hosts and the editor's limits. It is for wiring and the exchange's facts only: what a person
  would change (the log level, the AI's web search, the site's own writing and its daily AI calls, the times the
  scheduled follow offers, how many items a page lists) is a field of the form. The form does not show an
  `operator_only` setting, and a change to one answers 422
  `settings_edit_refused` like an unknown path; the file, the load and the start's notices read it as before. Without any of them a whole number with both bounds is a `range`, or `steps` of round numbers when
  the bounds lie more than 100 apart, an enum a `choice`, a bool a `switch` and a text typed under `advanced`.
  `tests/test_settings_form.py` fails for a number that has neither steps nor both bounds.
  The fields come from the settings classes (`settings_fields` in `settings_loader.py`) with no field the environment
  owns (an API key, a database password), none the loader sets and none marked `operator_only`, so a setting added
  to a settings class appears on the page by itself. `tools/export_openapi.py` also writes each path with its control, group, options and unit to
  `frontend/src/shared/api/settings-fields.json`, and the frontend's i18n test requires a label and a help for each.
- A change is `{path, value}` for one field. The server writes it into the file in place: every other line, comment
  and key stays, a text with a line break is written as a block, a map or a list replaces the old one, and a setting
  the file leaves out is added under its section. A change to an unknown path, or one that cannot be written in
  place, answers 422 `settings_edit_refused`; changes that change nothing answer 200 and write nothing.

### What a save does

1. The new texts are checked the way the app starts, by the one function a start and a reload use too
   (`startup_settings`): the settings load, the trading setup, the accounts key (prod refuses to start without
   `ACCOUNTS_KEY`) and every offered AI provider's key. Refused, with a problem at each setting's path: a value the
   settings refuse, a change of `environment` or `audience`, which change only when the app restarts, and a lockout of
   the page: an `api.allowed_hosts` without the host the save was sent to, or an `api.settings_file_max_bytes` smaller
   than a settings file.
2. Every save needs the administrator's own password in the same request, so a stolen session alone changes no
   setting. Each try is counted before it is checked, under its own limit (`accounts.settings_password_failures` per
   administrator and address in `accounts.sign_in_window_minutes`), apart from the sign-in's.
3. The server opens the app on the new texts: the whole startup, the database (a database older than the code is
   refused, `just db-migrate`) and the broker login included, within `api.settings_build_timeout_seconds` (30), and its
   database must hold an active administrator account of the one saving. A failure writes nothing.
4. Each changed file is written, after a backup of its old text (`.settings-admin/backups/<file>/`, owner-only, the
   latest `api.settings_backups_kept`), with an audit line (`.settings-admin/audit.jsonl`) naming the administrator by
   user id and the settings it changed, never a value. The new settings are current from the next request on, and the
   server logs `Settings saved from the Web and reloaded: ...`. A request or a run that started earlier finishes on the
   settings it started with; the earlier settings close when the last of them ends.

An edit made on disk outside the app is loaded the same way within `api.settings_poll_seconds` (2), or kept as a
refusal in the server log while the server keeps its settings; refused files are tried again once a file changes. The
CLI loads the files again before it prints each menu, and once more after a choice that may send an order (menus 2, 3
and 4): when they changed while the menu waited, it says so and prints the menu again on them. Every setting a save or
a reload puts in place applies at once, `behavior.log_level` and `accounts.max_concurrent_runs` included (a run counts
against the cap of the settings it starts on). HOST, PORT, `.env` and the environment are not edited here, and neither
are the built-in strategies of `config/strategies/`, which the strategies page owns. A revision covers the two YAML
files only, so an edit of `config/strategies/*.json` or `.env` alone reaches the running app at the next reload of a
YAML file, or at a restart.

### Problems and refusals

- A problem is `{message, file, path, line, column, code, params}`; `file`, `path`, `line` and `column` may be `null` (a
  value from `.env`, the database or the broker). The page shows a problem at the field whose path is the problem's
  `path` or starts it (`ai.available_models.openai` at `ai.available_models`), and one no field holds above the form.
  No message holds a value. `code` names the refusal so a page can word it in its own language: pydantic's error type
  (`less_than_equal`, `enum`, `missing`, ...) or the app's own (`ai_key_missing`, `ai_model_id_missing`,
  `search_on_open_data`), with the values its words need in `params` (the schema's limits, a provider or a variable
  name, never the input). The app's other refusals have `code` `null` for now, and a page shows `message` for any code
  it has no words for, such as `value_error`, whose words are a validator's own.
- Every error answer of the API is `{detail, code}`: `detail` in words for a person, `code` a stable `ErrorCode` the
  page switches on (one per refusal, from `ERROR_ANSWERS` in `web/app.py`; never switch on `detail`). The settings
  page's: 403 `password_required` (no password), 403 `password_refused` (a wrong one; the session stays), 403
  `administrators_only` (a signed-in user who is not an administrator; still signed in), 403 `settings_file_refused` (a
  symlinked, outside or too large file), 404 `settings_file_missing`, 409 `settings_conflict` (the server reloaded its
  settings during the save, or another save wrote a file first: save again), 422 `settings_refused` with `problems` too
  (the app would not start with it; nothing saved), 422 `settings_edit_refused`, 422 `invalid_request` (a body that
  does not validate; `detail` is then FastAPI's list of fields), and 429 `sign_in_throttled` with `Retry-After` (too
  many wrong passwords).

## Orders from the Web

Full Cycle, specific-stock analysis, valuation and market data never order. `POST /v1/runs/buzz-scan`,
`/v1/runs/intraday` and `/v1/runs/{id}/manual-buy` (a manual BUY of a stock a finished specific-stock run reported,
with the user's shares) start menus 2 and 3 and menu 4's manual BUY on the account their `broker` query names for the
whole run, through the same order gates and trading journal as the CLI: the user's mock account by default, or SinoPac
for an administrator while the site's Shioaji login is up and `features.sinopac_ordering` shows the user ordering
there (`broker_pipeline`; 403 `feature_hidden`, `real_broker_refused` or `broker_unavailable` before the run starts). At
each order `BrokerAccessRule` checks again that the order reaches the broker the run chose, that
`features.sinopac_ordering`, as the settings file on disk holds it at that moment and not as the run's settings held it
at its start, lets the user order there (`RealBrokerOrdererRule`, `ORDERING_OFF` otherwise), that the
user is still an active administrator, that the login is up on the server `shioaji.server` names on disk at that
moment (`BrokerLoginRule`, `BROKER_SERVER_MISMATCH` otherwise), and `BuyLimitRule` holds every SinoPac BUY to `trading.max_order_value` and the day's to
`trading.max_daily_buy_value`. `GET /v1/account/brokers` answers what each start's confirmation names.

`POST /v1/runs/{id}/follow` follows a finished Full Cycle into the user's mock account, the only account it orders on, as a
run of its own (`Workflow.FOLLOW`) through the same order loop. `Audience.order_pricing` decides the price: a fresh
realtime quote in continuous trading on a personal site; on a public site, which has no realtime quote, the official
close of the last closed session while no session trades, on the mock broker only (`OrderPricing.OFFICIAL_CLOSE`).
The order-gate check drives it as route `F` on both audiences, with `P11_OFFICIAL_CLOSE` and `P12_FOLLOW_ONCE`.

Each user follows the ranking on one follow account (`User.ranking_follow_broker`), chosen on My settings
(`PUT /v1/rankings/follow/account`; `GET /v1/rankings/follow/schedule` answers it with the schedule): the mock account,
which a user who chose nothing has, or SinoPac's simulation account (below). One rule (`FollowAccountRule`) says which
accounts the site offers the user as one now and why it refuses theirs (`account.refusal`: `ordering_off`,
`not_simulation`, `broker_unavailable`), for the block, the button, the schedule and My settings alike.
`POST /v1/rankings/follow` brings that account to the monthly ranking's latest decision, as a run of its own
(`Workflow.RANKING_FOLLOW`) through the same order loop, gates and pricing as a follow of a run; its body names the
account the user confirmed, and one that is no longer the saved account answers 409 `follow_account_changed`. It sells each holding the ranking left, then buys each ranked stock the account lacks: the account's value over
the ranking's stocks, capped by its share of the cash the sales free, in whole lots of `analysis.lot_size`
(`RankingFollowRule`). A ranked stock already held is left as it is, so a second follow of the same decision answers
409 `nothing_to_follow`, and a stock whose order was refused stays open to the next follow. A ranking that ranks no
stock sells nothing. `GET /v1/rankings/follow` answers which account it is for (`account`), what that account holds
and lacks of the ranking, the holdings that left it, why a follow may not start there now (`refusal`), whether a run of
the user runs now, and the mock account's return since its first ranking follow against `ranking.benchmark_id` over the
same sessions, from the close before that follow (none while the follow account is SinoPac, whose history the site does
not keep). Both need the `ranking` feature; the read needs the follow account's own feature (`mock_account`,
`sinopac_account`) and the follow its ordering feature (`mock_account`, `sinopac_ordering`). The ranking's backtest buys at the open of the session after the decision and resets every
holding to an equal weight each month; a follow buys at the price of the moment it is started, in whole shares, and
keeps the holdings that stay, so the two results differ. The order-gate check drives it as route `K`, with
`P17_RANKING_FOLLOW`.

On a follow account of SinoPac the follow brings SinoPac's simulation account to the ranking, through the order path
every SinoPac order takes (`BrokerAccessRule`, the ordering switch asked again before each exchange order, the
journal first, one order per stock). A ranking follow never orders with real money: `SimulationOnlyRule` refuses it
unless the Shioaji login that answers is on SinoPac's simulation server, when the run starts and before the account
is read (403 `not_simulation`), at each order's preparation and right before each exchange order (`NOT_SIMULATION`),
and no setting lifts it. It needs an active administrator whom `features.sinopac_ordering` shows ordering and the
login up; `GET /v1/rankings/follow` reads its positions in one request, and only while the site lets the user follow
there. Each BUY is sized inside `trading.max_order_value`; one past `trading.max_daily_buy_value` is refused,
recorded and left to a later follow. A user's schedule (`PUT /v1/rankings/follow/schedule`, `time` alone) follows on
the follow account, and saving either never changes the other. A decision is finished on the account its follow ran
on, and a user the site does not let follow on their account now is refused there, by the button (403
`real_broker_refused`, `feature_hidden`, `broker_unavailable` or `not_simulation`) and by the schedule (the timer logs
why), and never followed on the mock account instead.

One run at a time holds per server process only. A CLI on the same database can run beside it; on the mock broker
that can race the mock account's cash, which `formal-verify-order-gate` lists as not covered.

## Feature matrix

The navigation leads with the monthly ranking, then the market overview and the valuation. The runs, the strategy
library, the backtest and the formula designer are one section, Technical strategies, folded until the reader opens it;
every one of them works as before. All three built-in strategies lost money in a backtest, so one, `balanced`, ships.

| Feature | Status |
| --- | --- |
| Strategy library and formula designer | Live: the built-in and catalog from the API, owner strategies saved with revisions, copy, delete, select for runs and Buzz. |
| Full Cycle and specific-stock runs | Live: start after confirming the AI cost, state polled until it ends, paged history, decisions, orders, reports saved with the run. |
| Buzz and Intraday runs | Live on the account the start's confirmation chooses: the mock account, or SinoPac for an administrator while its login is up. |
| Manual BUY | Live on a finished specific-stock run's page: the shares, the account and a confirmation that names SinoPac's server and limits. |
| Watchlist | Live: names, types and expiry; MANUAL add and remove with rollback on refusal. |
| Stock search and stock page | Live: listing search, cached daily bars, the active strategy's evaluation and indicator readings from the backend. No realtime quote on the Web. |
| Market overview | Live: the TAIEX daily trend over 1M to 1Y (TWSE's own monthly index reports on a personal site, kept like a stock's history, or the open-data archive on a public one; any listed stock or ETF can replace it through `?target=`), the latest session's most traded stocks, and its breadth: advancers, decliners and unchanged stocks from the TWSE and TPEX listings' own change, and each industry's counts and average change, industries from the company profiles. The TPEx Index is kept only to adjust the TPEX stocks' history, and not shown. |
| Valuation | Live: market reference, specific stocks at a target P/E, undervalued scan with an explicit technical step, AI explanation per confirmed click. |
| Mock account | Live: positions, P&L, equity curve and as-of. |
| SinoPac account | Live at `/account/sinopac` for an administrator: `GET /v1/account/brokerage` answers which server the login is on (simulation or the real account), whether it is up and whether the site may order there, and the account as the broker reports it: balance, settlements, positions with the broker's prices and unrealized P&L, today's deals, past sales with their realized P&L. It never orders; ordering is `features.sinopac_ordering`, off by default. |
| My holdings | Live at `/holdings`: `GET /v1/holdings` answers the SinoPac account's, the mock account's and the hand-entered holdings as one portfolio, each holding under its source, at the last closes held, with each stock's ranking score or the reason it has none, the concentration, the share in the ranking's top and the value-weighted score. Hand entry through the stock search; a watched stock can be added as a holding. Analysis, not advice. |
| World | Live at `/world` and in the home page's World block: `GET /v1/world` answers each held world indicator's newest reading with its change, the written world briefs of the latest days, each sentence with the held items it cites and the listed stocks a cited item names, and the newest kept world news items with their publisher, time, address and the feed's own summary. It asks no feed and no AI: the Web API's world timer reads the feeds and writes the day's brief. Private. |
| Backtest | Live at `/backtest`: `POST /v1/backtests` replays the user's active strategy over held daily history with the live trading rules on the technical score alone, saves it per user (`accounts.saved_backtests`), and never orders; `GET /v1/backtests/options` names the period. The page shows the return against the TAIEX, each trade and the saved backtests. |
| Monthly ranking | Live at `/ranking`: `GET /v1/rankings/latest` answers the stocks the ranking picks at the latest decision the held history holds, and `GET /v1/rankings/backtest?first=&last=` replays it against `ranking.benchmark_id`; neither saves or orders. The page shows the stocks with both factors in words, what changed since the month before, the record against the benchmark with its caveats, and every past decision. The API answers no `ranking.*` setting, so the page derives the decision day from the decisions it sees and words the factor windows (3 and 12 months, a year of sessions) as the defaults. With the `mock_account` feature the page also holds the ranking in the mock account (`GET`/`POST /v1/rankings/follow`, below). All are signed-in: the ranking's sources are for a personal site. |
| Settings administration | Live: the settings of `appsetting.yaml` an administrator changes and the AI prompts as one form generated from the server's fields, with no YAML; a value out of bounds held at its field, a save with the administrator's password that runs at once, each refusal shown at its setting; an edit on disk loaded by the server. |
| Hot reload | A Web save applies at once; an edit made on disk applies within `api.settings_poll_seconds`, or is reported when the app would not start with it. |
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
| R2 | P2 | A save could pass validation and still stop the next start: an AI provider without its key, or a log level loguru does not know. | `AiConfig.missing_keys()` in the save check, for every offered provider since; `log_level` is a loguru level. Two cases in `test_a_file_the_app_would_refuse_is_never_saved`. |
| R3 | P2 | `Transfer-Encoding: gzip, chunked` slipped past the body limit. | Any `Transfer-Encoding` answers 413. `test_a_body_without_a_plain_length_is_refused`. |
| R4 | P2 | A history backfill recorded its window for stocks the source skipped, so they were not asked again. | Windows only for stocks that came back. `test_a_window_is_recorded_only_for_stocks_the_source_answered`. |
| R5 | P2 | Two requests caching the same new stock at once could hit a unique-key error (`merge` selects, then inserts at commit). | The cache's writes run one at a time per process. Not reproduced in a test; across processes (CLI and server) the race remains. |
| R6 | P2 | `test_claude_refuses_to_start_without_its_key` read the machine's `.env`. | The test clears the key itself; the admin tests set the provider key they need. |
| R7 | P3 | After a 401 on a watchlist toggle the rollback put the private list back into the cache. | No rollback once the token is gone. |
| R8 | P3 | A change that would make a settings file too large answered 500. | It is a refused edit (422). |

R1's allowlist went with the whole-file editor (2026-11-04). The form that replaced that editor (2026-11-07) writes
only the settings the server lists as fields, through the same checks, password and startup (`tests/test_web_admin.py`).

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

- Sign-in with Google is proven against a stand-in for Google only. The round trip with the real Google, and whether
  Google returns `auth_time` for a settings confirmation, wait for the owner's OAuth client.
- An account that signs in with Google is matched by its email. While registration is open, a person can register
  another person's address with a password first. The first sign-in with Google then removes that password, but what
  the person saved in the account stays there.
- `bun audit` still lists deepmerge (low, no fixed release) and minimatch (moderate) under the `shadcn` CLI, a
  development tool that never reaches the browser or the production install (`bun audit --prod` finds nothing).
- pip-audit still lists filelock (fix needs a major).
- `GET /v1/market/stocks/{id}` and `/v1/market/indexes/{index}` are public and, on a personal site, fetch the sessions
  the history cache lacks from the exchanges' sites, each question at most once per retry interval and nothing for a
  retry interval after a request failed; put a rate limit in the reverse proxy before exposing them.
- A settings save that answers 409 reloads the file, and the administrator's unsaved changes go with it; the message
  says to make the change again. The strategy designer keeps its draft instead.
- Settings saves and reloads are serialized by the runtime switch's lock inside one server process, and the revision is
  checked again just before the replace. A hand edit of the file in the instant between that check and the rename
  would be lost, and the directory is not synced after the replace, so a power cut right after a save can bring back
  the previous file (never a partial one); the next disk check then reloads what is there.
- A retired runtime's HTTP clients (PTT, Tavily, the news providers) are released by the garbage collector, not closed,
  when it closes; its database and its broker login are closed.
