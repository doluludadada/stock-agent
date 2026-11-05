# Stock Agent frontend guide

How the Stock Agent web UI is organised. It applies the principles of the Duoary
`frontend_architecture_guide.md` (feature ownership, one-way dependencies, central i18n and
design tokens) to this product. The backend rulebook stays `../../docs/clean_architecture_guide.md`;
its section 0 also decides here: less code that a reader understands at a glance wins.

## Status

The app runs on the backend Web API through same-origin `/v1` requests. Market data, strategies, runs, the
watchlist, valuation, the mock account and the settings files come from the server. The owner and the administrator
unlock with their tokens, kept in the tab's memory only.
See `../../docs/web-integration.md` for scopes, the feature matrix and the review, and `deployment.md` for production.

## Layout and dependency direction

```text
src/
  app/            routes, layout shell, providers; composes features
  features/
    market-overview/   the research target's trend (the TAIEX unless `?target=` names a stock or ETF), the most
                       traded stocks, the session's breadth and industry moves, the strategy slot
    strategies/        strategy model, API mapping, library, formula designer
    runs/              start runs, follow their state, history and run details
    valuation/         P/E valuation, undervalued scan, AI explanation on request
    watchlist/         server watchlist and its toggle button
    account/           mock account, positions and equity curve
    admin-settings/    the administrator's settings-file editor
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
| Listing search, most traded, breadth, stock and index bars | `shared/api/market.ts` | `/v1/market` |
| A stock's evaluation by the active strategy | `stock-research/api.ts` | `/v1/market/stocks/{id}/technical` |
| Built-in strategies, owner settings, saves with revisions | `strategies/api/queries.ts` | `/v1/technical-settings` |
| Runs, decisions, orders | `runs/api.ts` | `/v1/runs` |
| Watchlist | `watchlist/api.ts` | `/v1/watchlist` |
| Valuation | `valuation/api.ts` | `/v1/valuation` |
| Account | `account/api.ts` | `/v1/account/history` |
| Settings files | `admin-settings/api.ts` | `/v1/admin` |

Server state lives in TanStack Query. Query keys start with their scope (`public`, `owner`, `admin`), so a scope's
data is dropped when its token changes or the server rejects it. A 401 forgets only the token its request carried, so a
late refusal of an old token never locks out the one typed since. Answers the backend computes with the saved strategy
(the stock page's evaluation, the valuation scan) start with `['owner', 'strategy-results']`
(`shared/api/query-keys.ts`); every strategy save, switch or 409 resets them, so no page shows a result of the strategy
that was replaced. The mock account and the watchlist start with `['owner', 'run-results']`, and the poll that sees a run
end reloads them. A failed request shows its error; nothing falls back to generated data.

## Rules from the contract, defaults and display counts

- Stock ids (letters and digits, at most 10, lists of at most 20) are `shared/lib/stock-ids.ts`; runs, valuation, the
  watchlist and the overview's `?target=` parse with it. Chart ranges, the sessions to ask for and the range summary are
  `shared/lib/chart-range.ts`, shared by the overview and the stock page. Valuation bounds are `valuation/model.ts`.
  Each has a test that compares it with `openapi.json`.
- Form starting values (a target P/E of 15, a 30% margin, the TAIEX research target, the 3-month range) are named as
  defaults where they are used. Display counts (rows shown, page size) stay next to their component.
- Business settings are the backend's settings files, edited on `/admin/settings`; the UI does not copy them.

## Local persistence

Only the theme and the locale stay in `localStorage` (`stock-agent.theme`, `stock-agent.locale`).

## Design system

- `styles/tokens.css` is the only place for raw colors, fonts, radii, shadows and layout sizes.
  Dark ink/graphite is the default theme; the light theme is complete.
- `styles/globals.css` maps tokens to Tailwind and shadcn roles, and adds product roles (`up`, `down`,
  `jade`, `gold`) and chart roles (`--chart-*`).
- Every bordered block is a `Panel` (`shared/ui/panel.tsx`): a title bar over its content, 8 px corners, no shadow in
  the dark theme. Figures in a row use `Stat`; chart ranges use `RangeTabs`. A page has one title (`.display`, 20 to
  24 px); panel titles are 14 px.
- Grids align items to the start, so a short panel never stretches to its neighbour's height. An empty, locked or
  failed state inside a panel is a compact `StateBlock` with no frame of its own; a figure the backend has no source
  for is one line that says so.
- No decorative motion: no entrance animations, glows, spotlights or textures. Motion is kept where it explains a
  change, such as a rule card added to or removed from the designer.
- Market colors follow Taiwan usage: red is up, green is down. Every change also shows a sign,
  an arrow or hidden text, so color is never the only signal. Brand accents are separate.
- Numbers use tabular figures (`.tabular`). Chinese text falls back to system CJK fonts when the
  web fonts fail.
- Price and volume are two synced charts (`shared/ui/price-volume-chart.tsx`), never one chart
  with two y-axes.
- Motion respects `prefers-reduced-motion` through `MotionConfig reducedMotion="user"` and a CSS fallback.

`shared/ui/` holds vendored shadcn/ui sources and the project's own primitives (`panel`, `stat`, `range-tabs`,
`state-block`, `page-header`, `price-volume-chart`, `price-trend`, `stock-picker`, `confirm-dialog`, `stock-ids-problem`). Lint relaxes only fast-refresh and a few a11y role rules there,
to stay close to upstream.

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
| `bun run test` | Vitest unit tests (model, storage, i18n, boundaries) |
| `bun run build` | production build |
| `bun run e2e` | Playwright against a running backend (`E2E_API_URL`, `E2E_API_TOKEN`, `E2E_ADMIN_TOKEN`) |
| `bun run api:types` | regenerates `shared/api/schema.gen.ts` from `openapi.json` |

CI runs the first four plus E2E in `.github/workflows/frontend.yml`. The root `just frontend-check`
runs the first four locally.
