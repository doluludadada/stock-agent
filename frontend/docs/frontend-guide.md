# Stock Agent frontend guide

How the Stock Agent web UI is organised. It applies the principles of the Duoary
`frontend_architecture_guide.md` (feature ownership, one-way dependencies, central i18n and
design tokens) to this product. The backend rulebook stays `../../docs/clean_architecture_guide.md`;
its section 0 also decides here: less code that a reader understands at a glance wins.

## Status

The app runs on the backend Web API through same-origin `/v1` requests. Market data, strategies, runs, the
watchlist, valuation, the mock account and the settings files come from the server. Each person signs in with their
own account: the server keeps the session in an HttpOnly cookie, and every user has their own watchlist, mock
account, runs and strategies. A fresh site opens on the first-time setup, which needs the code the backend printed on
its console.
See `../../docs/web-integration.md` for scopes, the feature matrix and the review, and `deployment.md` for production.

## Layout and dependency direction

```text
src/
  app/            routes, layout shell, providers; composes features
  features/
    auth/              first-time setup, sign-in, registration, the account menu, My settings (the user's AI model)
                       and the administrator's users page
    market-overview/   the research target's trend (the TAIEX unless `?target=` names a stock or ETF), the most
                       traded stocks, the session's breadth and industry moves, the strategy slot
    strategies/        strategy model, API mapping, library, formula designer
    runs/              start runs, follow their state, history and run details; a finished Full Cycle's follow into
                       the mock account, and each decision marked followed or open
    backtest/          the active strategy replayed over a past period: the form from the server's options, the verdict
                       against the TAIEX, both curves as returns on one chart, the trades, and the saved backtests
    ranking/           the monthly ranking by revenue acceleration and nearness to the high: the stocks it picks now and
                       what changed since the month before, its backtest against the benchmark over a chosen period (the
                       answer in a sentence, both curves, every year), the caveats the research measured, and every past
                       decision with what it held
    valuation/         P/E valuation, undervalued scan, AI explanation on request
    watchlist/         server watchlist and its toggle button
    account/           mock account: the total P&L since it opened, positions, equity curve, the trades with the run
                       each came from, and the mock account panel of My settings (starting capital and the reset);
                       a switch to the SinoPac account where the user may order there
    admin-settings/    every setting of appsetting.yaml and the AI prompts of instructions.yaml as one form, generated
                       from the server's fields; a save with the password applies at once
    stock-research/    stock page, backend evaluation and readings, the archived financials
    attribution/       the open data's providers, datasets and license, which every page's footer links to
  shared/         typed HTTP transport, session and public market data (api/), URL builders (config/), generic UI,
                  formatters, theme, stock id and chart range rules
  i18n/           dictionaries per locale and namespace, language switching
  styles/         tokens.css (raw values) and globals.css (Tailwind/shadcn mapping)
```

- Dependencies point `app -> features -> shared`. `i18n` and `styles` are foundations.
- A feature never imports another feature. `app/router/routes/*` passes render slots between them; for example the
  run detail page receives `renderWatch` from the watchlist feature, and My settings receives `mockAccount` from the
  account feature. URL builders are shared config
  (`shared/config/paths.ts`): features link with them, and routes pass no hrefs.
- Code outside a feature uses only its `index.ts`.
- `shared` and `i18n` never import `app` or a feature.
- `tools/check-boundaries.ts` enforces these rules for alias and relative imports. It also
  rejects raw colors in app and feature code, `href="#"` placeholders and empty click handlers.
  It runs in `bun run lint` and in `tools/check-boundaries.test.ts`.

### Why the formula designer lives in `strategies`

The brief suggested separate `strategies` and `strategy-builder` features. The library and the
designer read and write the same `Strategy` model, so splitting them would force either a
cross-feature import or a second copy of the model. They are one feature with `model/`,
`library/` and `builder/` folders instead.

### Inside a feature

Each feature owns its types, fixtures, pure transformations, interaction state and screens.
Pure code (`model.ts`, `model/`) has no React, storage or DOM access. Ids and the current time
are passed in, so the same functions run in unit tests. Folders exist only where they hold
real code; there are no empty `api/` or `hooks/` layers.

## The strategy model

`features/strategies/model/types.ts` is the editor's formula model. Its vocabulary (kinds, parameters, outputs,
operators, effects) is the backend's, taken from the generated contract (`@/shared/api`, `schema.gen.ts`); a type test
in `api/mapping.ts` fails to compile when the indicator shapes drift. The editor adds an id to every rule and
condition, writes constants as tagged nodes and keeps a lone comparison as a `bare` group; `api/mapping.ts` is the one
place that converts, and `mapping.test.ts` round-trips the built-in strategies of `config/strategies` exactly.

All edits go through `applyEdit` (`model/edit.ts`). Validation (`model/validate.ts`) returns errors the backend would
refuse and warnings it allows (mixed units); only errors block a save. The readable preview (`model/describe.ts`) is
generated from the formula every time. `model/catalog.ts` carries the backend's bounds and outputs, checked against
the contract by `catalog.test.ts`.

## Data and its owners

| Data | Owner | Source |
| --- | --- | --- |
| Listing search, most traded, breadth, stock and index bars, many stocks' quotes and names | `shared/api/market.ts` | `/v1/market` |
| The site's audience and what it allows; the open-data archive's warm-up | `shared/api/audience.ts`, `shared/api/market.ts` | `/v1/market/audience`, `/v1/market/archive-status` |
| The brokers the user may choose now, the mock account first, a real one with its server and BUY limits | `shared/api/brokers.ts` | `/v1/account/brokers` |
| A stock's evaluation by the active strategy | `stock-research/api.ts` | `/v1/market/stocks/{id}/technical` |
| A stock's archived quarters and monthly revenue | `stock-research/api.ts` | `/v1/market/stocks/{id}/financials` |
| The open data's providers, datasets and license | `attribution/api.ts` | `/v1/market/attribution` |
| Built-in strategies, owner settings, saves with revisions | `strategies/api/queries.ts` | `/v1/technical-settings` |
| Runs, decisions, orders; a start of Buzz or Intraday on the broker chosen | `runs/api.ts` | `/v1/runs` |
| A manual BUY of a stock a specific-stock run reported, on the broker chosen | `runs/api.ts` | `/v1/runs/{run_id}/manual-buy` |
| A run's follow into the mock account: what is open, the refusal, the follows so far; starting one | `runs/api.ts` | `/v1/runs/{run_id}/follow` |
| A backtest's options, a run that is saved, the saved backtests, one of them, a delete | `backtest/api.ts` | `/v1/backtests` |
| The latest monthly ranking; its replay over a period against the benchmark, with each decision's ranking and holdings | `ranking/api.ts` | `/v1/rankings/latest`, `/v1/rankings/backtest` |
| Watchlist | `watchlist/api.ts` | `/v1/watchlist` |
| Valuation | `valuation/api.ts` | `/v1/valuation` |
| Account of a broker: now, the curve, the opening and the total P&L (none at a real broker) | `account/api.ts` | `/v1/account/history` |
| A broker's trades (the mock account's since the opening), each with the run whose decision it carried out (the followed run for a follow) | `account/api.ts` | `/v1/account/trades` |
| The reset of the mock account with a new starting capital | `account/api.ts` | `/v1/account/reset` |
| The settings form: every setting with its kind, bounds, choices and value; a save of the changed ones | `admin-settings/api.ts` | `/v1/admin/settings` |
| Who is signed in, setup, sign-in, registration, sign-out | `auth/api.ts` | `/v1/auth` |
| The AI models the site offers the user, and the user's choice | `auth/api.ts` | `/v1/auth/me/ai-model` |
| The users directory and changes to a user | `auth/api.ts` | `/v1/admin/users` |

Server state lives in TanStack Query. Query keys start with their scope (`public`, `owner`, `admin`).
`shared/api/session.ts` mirrors who the server says is signed in (`GET /v1/auth/me` at start and whenever the tab comes
back into view): checking, signed out, or signed in with the user and the permissions of their role. Private queries
run only while someone is signed in, and the private scopes' cache is dropped whenever another user signs in, the user
signs out, the server ends the session or a role changes. The transport sends the cookie with every request and
`X-Requested-With: stock-agent` with every write (the API's CSRF check). A 401 is the only answer that signs the tab
out, and only the session it was sent in, so a late refusal never ends a session started since; a 403 means not
allowed and keeps the user signed in; a 429 says how long to wait. Every refusal carries a stable `code` next to its
`detail`; `ApiError.code` holds it, and a page that answers refusals differently switches on it, never on the words (a
403 can be a wrong password, a lost role or a refused file). `RequireSignIn` (`shared/ui/require-sign-in.tsx`)
says on each private page what signing in opens there, and tells a user without the permission that a page is for
administrators. Hiding a page is never the protection: the server checks every request. Answers the backend computes with the saved strategy
(the stock page's evaluation, the valuation scan) start with `['owner', 'strategy-results']`
(`shared/api/query-keys.ts`); every strategy save, switch or 409 resets them, so no page shows a result of the strategy
that was replaced. The mock account, the watchlist and what a run leaves open to follow start with `['owner', 'run-results']`, and the
poll that sees a run end reloads them. Starting a follow and a reset reload them too: a follow can end before its page
first asks, and a reset opens every decision to follow again. A failed request shows its error; nothing falls back to generated data.

Many stocks at once (the watchlist's quotes, the mock account's names) come from `useStockQuotes` and `useListedNames`:
each code's listing answers at once, and each daily history is asked under the stock page's own key, one after
another, because a burst of cold histories reaches Yahoo, which answers it with empty bars. A quote is the newer of
the listing's day and the history's last bar, and keeps its session, so a page never mixes sessions without saying so.

## What the site's audience allows

One codebase runs as the owner's personal site and as a public site on open data only. `GET /v1/market/audience`
answers the server's table of what its audience allows (`open_data_only`, `realtime_quotes`, `news_articles`, `mops`)
and how it prices an order (`order_pricing`), read once per tab. A follow of a run says its price from it: a realtime
quote, only in continuous trading, or the official close of the last session, only while no session trades. A navigation item (`NavItem.requires`) or a run kind (`KINDS` in `RunsPage.tsx`) names the capability
it needs, and shows only once the server said the site has it, so a public visitor never sees Buzz, Intraday, the
watchlist's Social buzz source or the valuation, even for a moment. A link to a page the site does not offer opens a short reason
(`RequireCapability` in `app/router/RouteFallbacks.tsx`), not a page whose requests the server refuses. Hiding is never
the protection: the server refuses each of them. On open data only, the market overview and the run results say how far
the archive has come (`ArchiveWarmUp`) until it holds the sessions the strategies need. Every page's footer says nothing
here is investment advice and links to the open data's credit, which its license requires; analysis results and the
stock page say it again beside the result (`NotAdviceNote`).

## Rules from the contract, defaults and display counts

- Stock ids (letters and digits, at most 10, lists of at most 20) are `shared/lib/stock-ids.ts`; runs, valuation, the
  watchlist and the overview's `?target=` parse with it. Chart ranges, the sessions to ask for and the range summary are
  `shared/lib/chart-range.ts`, shared by the overview and the stock page. Valuation bounds are `valuation/model.ts`.
  Each has a test that compares it with `openapi.json`.
- Form starting values (a target P/E of 15, a 30% margin, the TAIEX research target, the 3-month range) are named as
  defaults where they are used. Display counts (rows shown, page size) stay next to their component.
- Business settings are the backend's settings files, edited on `/admin/settings`; the UI does not copy them.

## Local persistence

The theme, the locale and the folded navigation sections the reader opened stay in `localStorage`
(`stock-agent.theme`, `stock-agent.locale`, `stock-agent.nav.opened`); each works for the visit when storage is
refused. The settings form
keeps its unsaved changes in the page only and asks before the page is left with one. The settings files hold no
secret: the server refuses one written into them, and its form shows none.

## Design system

- `styles/tokens.css` is the only place for raw colors, fonts, radii, shadows, chart heights and layout sizes. The
  light theme (paper canvas, white cards, ink) is the first look and the dark theme is as finished; the default
  follows the system. `styles/tokens.test.ts` fails when any text color drops under 4.5:1 on a surface or a tint in
  either theme, so it runs with every `bun run test`.
- `styles/globals.css` maps tokens to Tailwind and shadcn roles, and adds product roles (`brand`, `up`, `down`,
  `flat`, `gold`, `danger-soft`) and chart roles (`--chart-*`). The brand is blue, so no button, link, selection or
  status reads as a market move: red and green appear only on prices, changes and breadth.
- One type ladder: one page title (`.display`, 24 to 30 px), one hero figure (`.figure`, 32 to 44 px, in its market
  color), summary figures (`text-figure-sm`), card titles (`text-title`, 15 px), 14 px body and 12 px captions.
- Every card is a `Panel` (`shared/ui/panel.tsx`): a title, one line that says what the card answers, the content
  and an optional footer such as `ShowMore`. Its body is a size container, so content lays out by the card's width
  (`@md:`), not the window's. Every table is a `DataTable`: real column headers, rows at least 44 px tall, columns
  that step aside below a width (`from`), and on a phone the first cell carries what the hidden columns said.
- Figures in a row use `Stat`; a hero price uses `QuoteHeadline`; a choice among a few uses `Segmented` (chart
  ranges are `RangeTabs`); a range position uses `RangeMeter`; a breadth split uses `BreadthBar`. An empty,
  signed-out or failed state is a `StateBlock`; a figure the backend has no source for is one line that says so.
- A stock's volume reads in lots through `useFormat().lots` ("3.7萬張"); a price from an older session carries its
  date (`useFormat().closeOn`, "11/2 收盤").
- Navigation: a bottom tab bar under 768 px (ranking, market, search, watchlist, account, more), a rail of icons from 768 px
  and the full sidebar from 1024 px, all from one list (`app/layouts/navigation.ts`), which also feeds the search
  palette's pages. Every control is at least 44 px tall under 768 px. The list leads with the monthly ranking; the
  home page stays the market overview.
- A section marked `folded` (Technical strategies: the runs, the library, the backtest, the designer) shows only its
  name as a button until the reader opens it, in the sidebar, the rail and the phone's sheet of all pages alike. Open,
  it says why it is folded in one line (`nav.note.<key>`; the rail has no room for it). `showsItems` decides: a
  section also shows open while the reader is on one of its pages, and its button rests then, so a page's own entry
  never hides. The search palette lists every page whatever is folded. Each of the four pages says the same under
  its title with a link to the ranking (`shared/ui/technical-strategy-note.tsx`, through `PageHeader`'s `note`).
- No decorative motion: no entrance animations, glows, spotlights or textures. Motion is kept where it explains a
  change, such as a rule card added to or removed from the designer.
- Market colors follow Taiwan usage: red is up, green is down. Every change also shows a sign,
  an arrow or hidden text, so color is never the only signal.
- Numbers use tabular figures (`.tabular`). Chinese text falls back to system CJK fonts when the
  web fonts fail.
- The settings page is one form, with no YAML. The server answers every setting it reads from `appsetting.yaml` and
  the prompts of `instructions.yaml` as a field (`GET /v1/admin/settings`): its dotted path, its kind, its value, its
  choices and the schema's bounds. `admin-settings/form.ts` groups the fields by their YAML section (`sources` by its
  second key too) and gives each kind its control: a switch, a select, checkboxes, a number field with the bounds, a
  text field or box, a list one item per line, and JSON for a map or a nested list. A setting that changes only at a
  restart (`environment`, `audience`) shows as text with one line why. A number out of its bounds or JSON that does not
  parse is held at its field in the words of the server's refusal codes (`admin:refusal.<code>`), and a save the server
  refuses shows each problem at its setting. A setting the server adds later shows with no frontend change: its label
  `admin:form.field.<path>` and help `admin:form.help.<path>` are all it needs, and `i18n.test.ts` fails while either is
  missing in a locale for a path of `shared/api/settings-fields.json`, which `export_openapi.py` writes.
- Price and volume are two synced charts (`shared/ui/price-volume-chart.tsx`), never one chart
  with two y-axes. The moving averages' colors pass the dataviz validator against both price colors.
- Motion respects `prefers-reduced-motion` through `MotionConfig reducedMotion="user"` and a CSS fallback.

A backtest's page is its address: `/backtest?id=` names the saved backtest on screen. A run can take tens of seconds, so
its mutation has a key: the progress shows again on a page that was left and reopened, and the answer lands in the
cache and the saved list either way; the seconds waited so far show in a `ProgressNote`. A result and its benchmark are
one chart from the same start (`shared/ui/comparison-chart.tsx`), never two y-axes: the backtest draws returns around 0,
and the ranking draws what 1 put in is worth around 1. The benchmark's color (`--chart-benchmark`) passes the dataviz
validator's separation checks against `--chart-price` in both themes, and its line is dashed too.

The ranking page (`/ranking`) answers two questions side by side from 1280 px: which stocks the formula picks now, and
whether following it would have beaten the benchmark. Its rules:

- The address holds the period (`?period=5Y`, or `?first=&last=`; none is the whole history) and the decision whose
  stocks are open (`?month=` with the decision's date), so both survive a reload. `ranking/model.ts` reads and writes them.
- The first answer after a server start takes close to a minute and later ones seconds. The page asks for the latest
  ranking first and for the replays only once it answered, shows the seconds waited, keeps the period before on screen
  (dimmed) while the next one is computed, and keeps every answer for an hour (fresh for ten minutes). Typing two days
  asks nothing; the Apply button does.
- A curve that multiplies at least 4 times starts on a log axis with round multiples as ticks (`logAxis`), because a
  linear axis presses the benchmark flat; the reader can switch.
- What the API does not answer is derived in `ranking/model.ts` and said as an estimate where it is one: the stocks that
  entered and left come from a second replay of the last two decisions (`periodBefore`); the decision day is the
  earliest day of the month any decision seen fell on (`decisionDay`), and the next decision is the first weekday from
  that day of the next month, shown with "about"; each month's result is the curve's change from its decision to the next.
- The caveats (`CAVEATS`) are facts the research measured and the only performance figures written in the copy. Every
  other figure comes from the API.

`shared/ui/` holds vendored shadcn/ui sources and the project's own primitives (`panel`, `data-table`, `stat`,
`segmented`, `range-tabs`, `show-more`, `range-meter`, `breadth-bar`, `quote-headline`, `state-block`, `page-header`,
`technical-strategy-note`,
`field`, `password-input`, `avatar`, `price-volume-chart`, `price-trend`, `comparison-chart`, `progress-note`,
`stock-picker`, `confirm-dialog`, `stock-ids-problem`). Lint relaxes only fast-refresh and a few a11y role rules there, to stay close to upstream.

## Internationalization

Dictionaries live in `src/i18n/locales/<locale>/<namespace>.ts`. English is the canonical shape;
each zh-TW file is typed as `DictionaryShape<typeof en>`. Traditional Chinese is the default.
`i18n/i18n.test.ts` checks that both locales have the same keys, that every literal key in the
source exists, and that dynamic key families resolve. Dates and numbers use `Intl` with the
`Asia/Taipei` time zone (`shared/lib/format.ts`).

The built-in strategies' rule names are text, not keys, because they hold `.` and `:`.
`locales/zh-TW/rule-names.ts` maps each English name to its Chinese name. A rule's name is the owner's text and shows
as typed, with one exception: `useStrategyLabels().rule(strategyId, name)` reads a rule of a strategy with a built-in id
in the reader's language while its name is one the built-ins ship. It keys on the strategy, never on the name alone, so
a name the owner typed in their own strategy stays as typed even when a built-in rule has it; the run page reads the
run's strategy from `summary.technical_strategy_id`. The formula designer always shows the names as its fields hold
them, in the rule list and the preview alike, since that is the text a save keeps. A copy of a built-in saves the
names in the reader's language. `i18n.test.ts` fails when a rule in `config/strategies` has no Chinese name.

## Checks

| Command | What it does |
| --- | --- |
| `bun run lint` | oxlint plus the boundary checker |
| `bun run typecheck` | `tsc -b` for app, tests, E2E and tools |
| `bun run test` | Vitest unit tests (model, storage, i18n, boundaries, the palette's contrast in both themes) |
| `bun run build` | production build |
| `bun run e2e` | Playwright against a running backend (`E2E_API_URL`; `E2E_SETUP_CODE` on a backend with no user yet; `E2E_SETTINGS_DIR`, that backend's disposable `config/`, for the edits made on disk) |
| `bun run api:types` | regenerates `shared/api/schema.gen.ts` from `openapi.json` |

`bun tools/capture-screens.ts <out-dir> --url <app> [--user name --password pw]` signs in through the API and saves
every page at 375, 768, 1024 and 1440 px in both themes, with an audit of each (sideways scroll, controls under 44 px
on a phone, text cut off, page errors) in `audit.json`.

CI runs the first four in `.github/workflows/frontend.yml`, and the root `just frontend-check` runs them locally.
E2E needs a real backend, so it runs only on your machine. [README.md](../README.md#browser-flows-e2e) says how and why.
