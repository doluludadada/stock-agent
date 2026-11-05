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
    auth/              first-time setup, sign-in, registration, the account menu and the administrator's users page
    market-overview/   the research target's trend (the TAIEX unless `?target=` names a stock or ETF), the most
                       traded stocks, the session's breadth and industry moves, the strategy slot
    strategies/        strategy model, API mapping, library, formula designer
    runs/              start runs, follow their state, history and run details
    valuation/         P/E valuation, undervalued scan, AI explanation on request
    watchlist/         server watchlist and its toggle button
    account/           mock account, positions and equity curve
    admin-settings/    the settings files as text: the server's check as you type, a save with the password,
                       edits made on disk, history and restore
    stock-research/    stock page, backend evaluation and readings
  shared/         typed HTTP transport, session and public market data (api/), URL builders (config/), generic UI,
                  formatters, theme, stock id and chart range rules
  i18n/           dictionaries per locale and namespace, language switching
  styles/         tokens.css (raw values) and globals.css (Tailwind/shadcn mapping)
```

- Dependencies point `app -> features -> shared`. `i18n` and `styles` are foundations.
- A feature never imports another feature. `app/router/routes/*` passes render slots between them; for example the
  run detail page receives `renderWatch` from the watchlist feature. URL builders are shared config
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
place that converts, and `mapping.test.ts` round-trips the three built-in strategies of `config/strategies` exactly.

All edits go through `applyEdit` (`model/edit.ts`). Validation (`model/validate.ts`) returns errors the backend would
refuse and warnings it allows (mixed units); only errors block a save. The readable preview (`model/describe.ts`) is
generated from the formula every time. `model/catalog.ts` carries the backend's bounds and outputs, checked against
the contract by `catalog.test.ts`.

## Data and its owners

| Data | Owner | Source |
| --- | --- | --- |
| Listing search, most traded, breadth, stock and index bars, many stocks' quotes and names | `shared/api/market.ts` | `/v1/market` |
| A stock's evaluation by the active strategy | `stock-research/api.ts` | `/v1/market/stocks/{id}/technical` |
| Built-in strategies, owner settings, saves with revisions | `strategies/api/queries.ts` | `/v1/technical-settings` |
| Runs, decisions, orders | `runs/api.ts` | `/v1/runs` |
| Watchlist | `watchlist/api.ts` | `/v1/watchlist` |
| Valuation | `valuation/api.ts` | `/v1/valuation` |
| Account | `account/api.ts` | `/v1/account/history` |
| Settings files: the overview (polled), a revision's text (read once), checks, saves, backups, reload | `admin-settings/api.ts` | `/v1/admin/settings`, `/v1/admin/audit` |
| Who is signed in, setup, sign-in, registration, sign-out | `auth/api.ts` | `/v1/auth` |
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
that was replaced. The mock account and the watchlist start with `['owner', 'run-results']`, and the poll that sees a run
end reloads them. A failed request shows its error; nothing falls back to generated data.

Many stocks at once (the watchlist's quotes, the mock account's names) come from `useStockQuotes` and `useListedNames`:
each code's listing answers at once, and each daily history is asked under the stock page's own key, one after
another, because a burst of cold histories reaches Yahoo, which answers it with empty bars. A quote is the newer of
the listing's day and the history's last bar, and keeps its session, so a page never mixes sessions without saying so.

## Rules from the contract, defaults and display counts

- Stock ids (letters and digits, at most 10, lists of at most 20) are `shared/lib/stock-ids.ts`; runs, valuation, the
  watchlist and the overview's `?target=` parse with it. Chart ranges, the sessions to ask for and the range summary are
  `shared/lib/chart-range.ts`, shared by the overview and the stock page. Valuation bounds are `valuation/model.ts`.
  Each has a test that compares it with `openapi.json`.
- Form starting values (a target P/E of 15, a 30% margin, the TAIEX research target, the 3-month range) are named as
  defaults where they are used. Display counts (rows shown, page size) stay next to their component.
- Business settings are the backend's settings files, edited on `/admin/settings`; the UI does not copy them.

## Local persistence

Only the theme and the locale stay in `localStorage` (`stock-agent.theme`, `stock-agent.locale`). The settings editor
keeps an administrator's unsaved text in `sessionStorage` (`stock-agent.settings-drafts`), for that tab and that user
only, so a reload, an ended session or a visit to another page loses nothing; a save or a discard removes it. The
settings files hold no secret: the server refuses one written into them.

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
- Navigation: a bottom tab bar under 768 px (market, watchlist, search, account, more), a rail of icons from 768 px
  and the full sidebar from 1024 px, all from one list (`app/layouts/navigation.ts`), which also feeds the search
  palette's pages. Every control is at least 44 px tall under 768 px.
- No decorative motion: no entrance animations, glows, spotlights or textures. Motion is kept where it explains a
  change, such as a rule card added to or removed from the designer.
- Market colors follow Taiwan usage: red is up, green is down. Every change also shows a sign,
  an arrow or hidden text, so color is never the only signal.
- Numbers use tabular figures (`.tabular`). Chinese text falls back to system CJK fonts when the
  web fonts fail.
- The settings editor is CodeMirror 6: YAML highlighting, search, undo, and each problem the server locates marked
  at its line and column. Its colors are the tokens, and it loads only with the administrator's route.
- Price and volume are two synced charts (`shared/ui/price-volume-chart.tsx`), never one chart
  with two y-axes. The moving averages' colors pass the dataviz validator against both price colors.
- Motion respects `prefers-reduced-motion` through `MotionConfig reducedMotion="user"` and a CSS fallback.

`shared/ui/` holds vendored shadcn/ui sources and the project's own primitives (`panel`, `data-table`, `stat`,
`segmented`, `range-tabs`, `show-more`, `range-meter`, `breadth-bar`, `quote-headline`, `state-block`, `page-header`,
`field`, `password-input`, `avatar`, `price-volume-chart`, `price-trend`, `stock-picker`, `confirm-dialog`,
`stock-ids-problem`). Lint relaxes only fast-refresh and a few a11y role rules there, to stay close to upstream.

## Internationalization

Dictionaries live in `src/i18n/locales/<locale>/<namespace>.ts`. English is the canonical shape;
each zh-TW file is typed as `DictionaryShape<typeof en>`. Traditional Chinese is the default.
`i18n/i18n.test.ts` checks that both locales have the same keys, that every literal key in the
source exists, and that dynamic key families resolve. Dates and numbers use `Intl` with the
`Asia/Taipei` time zone (`shared/lib/format.ts`).

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

CI runs the first four plus E2E in `.github/workflows/frontend.yml`. The root `just frontend-check`
runs the first four locally.
