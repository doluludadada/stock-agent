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
                       decision with what it held; the ranking followed into the mock account
    valuation/         P/E valuation, undervalued scan, AI explanation on request
    watchlist/         server watchlist and its toggle button
    account/           mock account: the total P&L since it opened, positions, equity curve, the trades with the run
                       each came from, and the mock account panel of My settings (starting capital and the reset).
                       The SinoPac account on its own page, read only: which server, whether the site may order
                       there, and the account as the broker reports it
    holdings/          My holdings: the SinoPac account's holdings, the mock account's and the ones entered by hand as
                       one portfolio, each stock with its ranking score and revenue; the entry form
    admin-settings/    every setting of appsetting.yaml and the AI prompts of instructions.yaml as one form of choices,
                       generated from the server's fields; a save with the password applies at once
    stock-research/    stock page: the ranking score and the monthly revenue at the top, the financial analysis the backend
                       reads from held data (the reading in sentences, the revenue and earnings trends, the valuation
                       against its own history), the related news and discussion, the archived financials, the
                       strategy's evaluation
    attribution/       the open data's providers, datasets and license, which every page's footer links to
  shared/         typed HTTP transport, session and public market data (api/), URL builders (config/), generic UI,
                  formatters, theme, stock id and chart range rules
  i18n/           dictionaries per locale and namespace, language switching
  styles/         tokens.css (raw values) and globals.css (Tailwind/shadcn mapping)
```

- Dependencies point `app -> features -> shared`. `i18n` and `styles` are foundations.
- A feature never imports another feature. `app/router/routes/*` passes render slots between them; for example the
  run detail page receives `renderWatch` from the watchlist feature, My settings receives `mockAccount` from the
  account feature, and My holdings receives the `watched` stocks from the watchlist feature. The home page
  (`app/router/routes/home.tsx`) is composed the same way: each feature exports its own card (`MarketToday`,
  `RankingToday`, `HoldingsToday`, `WatchlistToday`), and the route lays them out. URL builders are shared config
  (`shared/config/paths.ts`): features link with them, and routes pass no hrefs.
- Code outside a feature uses only its `index.ts`.
- `shared` and `i18n` never import `app` or a feature.
- `tools/check-boundaries.ts` enforces these rules for alias and relative imports. It also
  rejects raw colors in app and feature code, `href="#"` placeholders, empty click handlers and
  `crypto.randomUUID`. It runs in `bun run lint` and in `tools/check-boundaries.test.ts`.
- A random id comes from `randomHex` (`shared/lib/random-id.ts`). The site also runs over plain http at a host
  name (`deployment.md`), where the browser gives the page no secure context and so no `crypto.randomUUID`.

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
| Whether the site needs its first administrator and takes registrations; whom it shows each feature to | `shared/api/features.ts` | `/v1/auth/status` |
| The brokers the user may choose now, the mock account first, a real one with its server and BUY limits | `shared/api/brokers.ts` | `/v1/account/brokers` |
| A stock's evaluation by the active strategy | `stock-research/api.ts` | `/v1/market/stocks/{id}/technical` |
| A stock's archived quarters and monthly revenue | `stock-research/api.ts` | `/v1/market/stocks/{id}/financials` |
| A stock's financial analysis from held data and its reading by fixed rules; what is said about it; its score, the place in the monthly ranking as a percentile | `stock-research/api.ts` | `/v1/market/stocks/{id}/analysis`, `/news`, `/ranking` |
| A stock's AI brief as the site holds it; a signed-in viewer's request to write today's | `stock-research/api.ts` | `/v1/market/stocks/{id}/brief` |
| The open data's providers, datasets and license | `attribution/api.ts` | `/v1/market/attribution` |
| Built-in strategies, owner settings, saves with revisions | `strategies/api/queries.ts` | `/v1/technical-settings` |
| Runs, decisions, orders; a start of Buzz or Intraday on the broker chosen | `runs/api.ts` | `/v1/runs` |
| A manual BUY of a stock a specific-stock run reported, on the broker chosen | `runs/api.ts` | `/v1/runs/{run_id}/manual-buy` |
| A run's follow into the mock account: what is open, the refusal, the follows so far; starting one | `runs/api.ts` | `/v1/runs/{run_id}/follow` |
| A backtest's options, a run that is saved, the saved backtests, one of them, a delete | `backtest/api.ts` | `/v1/backtests` |
| The latest monthly ranking; its replay over a period against the benchmark, with each decision's ranking and holdings; the ranking in the mock account, and the start of its follow | `ranking/api.ts` | `/v1/rankings/latest`, `/v1/rankings/backtest`, `/v1/rankings/follow` |
| Watchlist | `watchlist/api.ts` | `/v1/watchlist` |
| Valuation | `valuation/api.ts` | `/v1/valuation` |
| The mock account: now, the curve, the opening and the total P&L | `account/api.ts` | `/v1/account/history` |
| A broker's trades (the mock account's since the opening, the site's orders on SinoPac), each with the run whose decision it carried out (the followed run for a follow) | `account/api.ts` | `/v1/account/trades` |
| The SinoPac account as the broker reports it: which server, whether the login is up, whether the site may order there, and the statement | `account/api.ts` | `/v1/account/brokerage` |
| The user's holdings as one portfolio, from the sources chosen; a hand-entered holding kept or removed | `holdings/api.ts` | `/v1/holdings`, `/v1/holdings/manual`, `/v1/holdings/manual/remove` |
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
that was replaced. The mock account, the SinoPac account, the holdings, the watchlist and what a run leaves open to follow
start with `['owner', 'run-results']`, and the poll that sees a run end reloads them. Starting a follow and a reset reload them too: a follow can end before its page
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

The stock page opens with what needs no run and no session. A viewer the site does not show the `ranking` feature
gets no score block, and the page never asks for the score. `StockSummary` leads, right under the price: the ranking
score (0 to 100, the place among the scored stocks, the two factors' percentiles as bars, whether it is in the top, the
decision day, or the reason a stock has no score, and one line that the score measures and does not predict) and the
monthly revenue (the latest month, its change from a year before, the acceleration, and up to 36 months as bars that
resize with the card). On a phone the score comes first and both read at 360 px with no sideways scroll. `AnalysisPanel` shows the backend's analysis as it
answers it: every figure, streak and sentence kind is the backend's (`research:analysis.reading.kind.<kind>` says each
in the reader's language, with its count), and a figure the held history is too short for shows a dash with one line
that says how much is held. `BriefPanel` sits right under `StockSummary`, never above it: the AI's brief of the stock, which the site writes
once per stock and Taipei day for every viewer. `briefView` (`stock-research/brief.ts`) decides the one state the card
says: written, being written, failed, the day's limit reached, or not written. Only a signed-in viewer's click asks
for a brief, never a page open, since each one spends an AI call and one of the day's new briefs. A shown brief always
names the AI, the model, the Taipei time, the window and the close's change over it. A citation's name comes from its
kind and date, never from the AI's text, and a cited source leads to its own http address or to the page's part of
its kind (`SECTION_ANCHORS`). `NewsPanel` lists announcements, exchange news and, where the audience allows
`news_articles`, articles and board posts, as the site's article store keeps them, so the list reaches back past what
the sources serve today. Every title and text there is a third party's: it renders as text, and an
address is a link only when `outboundUrl` finds it plain http or https, opened with `rel="noopener noreferrer nofollow"`.

## What the administrator shows

The administrator gives each feature a visibility in the settings (`features.*`): off, administrators or everyone.
`GET /v1/auth/status` answers all of them, and `shows()` (`shared/api/features.ts`) decides for a viewer: everyone, or
administrators with the permission `see_administrator_features`; false until the server has said. The tab asks again
when it is back in focus a minute later, and at once when a request is refused with the code `feature_hidden`
(`app/providers/query-client.ts`), so a change reaches an open tab.

- `app/pages.ts` is the one table of pages with the features each belongs to (`PAGE_FEATURES`; any one of them shows
  the page, and a page that names none always shows). The navigation (`navSections`), the phone's tab bar, the search
  palette's pages and the routes (`page()` in `app/router/router.tsx`, through `RequireFeature`) all read it, and
  `app/pages.test.tsx` fails when a feature of the contract is named by no page.
- A feature that opens no page is listed in `FEATURES_WITHOUT_PAGE` with the reason. `sinopac_ordering` is the one:
  seeing the SinoPac account (`sinopac_account`, the `brokerage` page) and ordering on it are two features, so
  ordering is named at no page, or a viewer who sees ordering alone would be let into the account. The server's
  answers carry it: `/v1/account/brokers` offers SinoPac to a run only while it shows, and the account page says its
  state from `ordering`.
- A link to a hidden page answers the not-found page, which says nothing about what others see. The home page names
  no feature, so it always opens, and shows the card of each feature the viewer sees. The settings pages name no
  feature either, so no setting locks the administrator out.
- Inside a page: a run kind names its feature next to its capability (`KINDS`); the routes pass the watch button,
  My settings' mock account panel and My holdings' watched stocks only where their feature shows; the search goes with the stock pages; a follow needs the mock account; the SinoPac account links to My
  holdings only where that shows. The server leaves a hidden broker out of `/v1/account/brokers`,
  so a workflow that orders and the manual BUY show only while that list offers an account (`useBrokerOffers`), and a
  real broker alone still shows its server and limits.
- Hiding is never the protection here either: the server refuses every request of a hidden feature.

## Rules from the contract, defaults and display counts

- Stock ids (letters and digits, at most 10, lists of at most 20) are `shared/lib/stock-ids.ts`; runs, valuation, the
  watchlist and the overview's `?target=` parse with it. Chart ranges, the sessions to ask for and the range summary are
  `shared/lib/chart-range.ts`, shared by the overview and the stock page. Valuation bounds are `valuation/model.ts`.
  The bounds of a hand-entered holding (whole shares up to 1e9, a cost above 0 up to 1e6) are `holdings/model.ts`.
  Each has a test that compares it with `openapi.json`.
- Form starting values (a target P/E of 15, a 30% margin, the TAIEX research target, the 3-month range) are named as
  defaults where they are used. Display counts (rows shown, page size) stay next to their component.
- Business settings are the backend's settings files, edited on `/admin/settings`; the UI does not copy them.

## Local persistence

The theme, the locale and the folded navigation sections the reader opened stay in `localStorage`
(`stock-agent.theme`, `stock-agent.locale`, `stock-agent.nav.opened`); each works for the visit when storage is
refused. The settings form and the formula designer keep their unsaved changes in the page only and ask before the
page is left with one. When the session ends under them (a 401, a sign-out in another tab), the sign-in prompt
replaces the page, so `useKeptDraft` (`shared/lib/kept-draft.ts`) keeps the draft in memory and hands it back when the
same user opens the page again; another user never gets it. The settings files hold no
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
- A page composes shared parts and never spaces or frames itself. Its root is `.page-stack` (the header and the
  blocks, `--space-page` apart); cards side by side are a `.card-grid` and cards under one another a `.card-stack`
  (`--space-grid`); the page names only its columns. `PageHeader` is the top of every page: the section above the
  title comes from the navigation (`PageSectionProvider` in the shell), so no page names its own, and the header names
  the browser tab `<title> · Stock Agent` (`usePageTitle`, which a page with its own heading calls itself: the stock
  page, a run, the designer, the sign-in screens). After a navigation the shell moves the focus to `<main>`.
- One pattern for a page that has nothing to show yet. Loading is a `PageSkeleton` (a card inside a page uses a
  `Skeleton` of its content's height). Empty, signed out, refused and failed are a `StateBlock`, `framed` where it
  stands alone on the page. A failed request is an `ErrorState`, whose words come from `useErrorReason`
  (`shared/lib/error-reason.ts`): by the refusal's code where the app has words for it (`common:refusal.<code>`), else
  by the kind of failure, never the server's own English sentence.
- A link or a button inside running text takes `.tap`, which makes it 44 px tall under 768 px. A card's way to the
  page that holds the rest is a `PanelLink` in its title row.
- Every card is a `Panel` (`shared/ui/panel.tsx`): a title, one line that says what the card answers, the content
  and an optional footer such as `ShowMore`. Its body is a size container, so content lays out by the card's width
  (`@md:`), not the window's. Every table is a `DataTable`: real column headers, rows at least 44 px tall, columns
  that step aside below a width (`from`), and on a phone the first cell carries what the hidden columns said.
- Figures in a row use `Stat`; a hero price uses `QuoteHeadline`; a choice among a few uses `Segmented` (chart
  ranges are `RangeTabs`); a range position uses `RangeMeter`; a breadth split uses `BreadthBar`. An empty,
  signed-out or failed state is a `StateBlock`; a figure the backend has no source for is one line that says so.
- A stock's volume reads in lots through `useFormat().lots` ("3.7萬張"); a price from an older session carries its
  date (`useFormat().closeOn`, "11/2 收盤").
- Navigation: a bottom tab bar under 768 px (today, ranking, search, holdings, more), a rail of icons from 768 px
  and the full sidebar from 1024 px, all from one list (`app/layouts/navigation.ts`), which also feeds the search
  palette's pages. Every control is at least 44 px tall under 768 px. The order is the product's: Today (the home
  page), Research (the monthly ranking, the market overview), Mine (My holdings, the watchlist, the SinoPac account
  for a user with `use_real_broker`, My settings), Other tools, Administration. An entry shows by the viewer's
  permission (`needs`), the site's audience (`requires`) and the features of its page (`app/pages.ts`); a tab of the
  bar whose page is hidden leaves the bar.
- The home page (`/`, "Today") answers what to look at now, from what the other pages already ask the server: the
  index and the session's breadth in one row, this month's ranking (10 stocks beside the other cards, 5 in one
  column), the portfolio's figures and the watchlist's day. Each card is its feature's, leads to its page, and says
  its own loading, empty and failed state. The ranking decides once a month and the holdings may be empty, so neither
  alone is the home page. A visitor gets the public cards and one invitation to sign in. The market overview is
  `/market`.
- A section marked `folded` (Other tools: the runs, the mock account, the valuation, the library, the backtest, the
  designer) shows only its name as a button until the reader opens it, in the sidebar, the rail and the phone's sheet
  of all pages alike. They are the pages the site shows administrators only by default. Open, it says why it is folded
  in one line (`nav.note.<key>`; the rail has no room for it). `showsItems` decides: a section also shows open while
  the reader is on one of its pages, and its button rests then, so a page's own entry never hides. The search palette
  lists every page whatever is folded. Each of the four technical-strategy pages says under its title that the
  strategies did not profit, with a link to the ranking (`shared/ui/technical-strategy-note.tsx`, through
  `PageHeader`'s `note`).
- No decorative motion: no entrance animations, glows, spotlights or textures. Motion is kept where it explains a
  change, such as a rule card added to or removed from the designer.
- Market colors follow Taiwan usage: red is up, green is down. Every change also shows a sign,
  an arrow or hidden text, so color is never the only signal.
- Numbers use tabular figures (`.tabular`). Chinese text falls back to system CJK fonts when the
  web fonts fail.
- The settings page is one form of choices, with no YAML. The server answers the settings an administrator changes
  from the web and the prompts of `instructions.yaml` as a field (`GET /v1/admin/settings`). A setting only an
  operator editing the file needs (`operator_only` in its settings class: addresses, column names, patterns, folders,
  the exchange's hours and ticks) is no field, and a save that names one is refused.
  Each field carries: its dotted path, its
  kind, its group, its value and what the control offers. The control comes from the kind alone, with no code per
  setting: a switch; a choice as a row of buttons (`Segmented`) up to four options and a list above; checkboxes; a
  list of steps, each said with its unit (`admin:form.unit.<unit>`, a `percent` fraction as a percentage); a range as
  a slider with minus and plus buttons and its value as text, the buttons alone where the range has no upper or lower
  end; a date; a time. Only `text`, `lines` (one item per line) and `structure` (JSON) are typed, and the server puts
  all of them in the group `advanced`.
- A value in the file that is none of the options or steps, or between two steps of a range, still shows, marked as
  the current custom value, and stays listed so picking it again changes nothing. A save sends only the settings the
  administrator touched whose value differs (`changesOf`), so such a value survives the save of another setting. A
  setting that may be unset offers "not set", which sends null.
- The groups show in the contract's order (`GROUPS` in `admin-settings/form.ts`), each a card with a title and one
  line (`admin:form.group.<group>`), its settings in the server's order under a sub-heading per YAML section
  (`admin:form.section.<key>`, and `admin:form.heading.<key>` for the second key of `sources`). A list of the groups
  under the search jumps to each. Every group folds on a click of its title. `advanced` starts folded, and under
  768 px every group but the first does, since the form is one long column there; a group opens when the
  administrator opens it or jumps to it, a search finds a setting in it or a problem sits in it.
- A setting that changes only at a restart (`environment`, `audience`) shows as text with one line why. JSON that does
  not parse is held at its field in the words of the server's refusal codes (`admin:refusal.<code>`), and a save the
  server refuses shows each problem at its setting. A setting the server adds later shows with no frontend change: its
  label `admin:form.field.<path>` and help `admin:form.help.<path>` are all it needs, and `i18n.test.ts` fails while
  either is missing in a locale for a path of `shared/api/settings-fields.json`, which `export_openapi.py` writes; the
  same test requires every group, unit and option of that file.
- My settings' mock account offers starting capitals to choose (`STARTING_CAPITALS` in `account/model.ts`) and keeps a
  capital that is none of them as the current one.
- Price and volume are two synced charts (`shared/ui/price-volume-chart.tsx`), never one chart
  with two y-axes. The moving averages' colors pass the dataviz validator against both price colors.
- Motion respects `prefers-reduced-motion` through `MotionConfig reducedMotion="user"` and a CSS fallback.

A backtest's page is its address: `/backtest?id=` names the saved backtest on screen. A run can take tens of seconds, so
its mutation has a key: the progress shows again on a page that was left and reopened, and the answer lands in the
cache and the saved list either way; the seconds waited so far show in a `ProgressNote`. A result and its benchmark are
one chart from the same start (`shared/ui/comparison-chart.tsx`), never two y-axes: the backtest draws returns around 0,
and the ranking draws what 1 put in is worth around 1. The benchmark's color (`--chart-benchmark`) passes the dataviz
validator's separation checks against `--chart-price` in both themes, and its line is dashed too.

The ranking page (`/ranking`) leads with the stocks the formula picks now (`LatestRanking.tsx`), because they are
what the reader came for. From 1280 px, beside them are the ranking in the mock account (`MockAccountFollow.tsx`)
and whether following the ranking would have beaten the benchmark, which every title names a backtest and simulated.
Narrower, they follow them. The operator's command (`just backfill-history`) shows only to a viewer with
`see_administrator_features`. Its rules:

- The mock account's block shows only where the site shows the viewer the mock account: the route hands
  `mockAccount` in, and without it the page never asks `/v1/rankings/follow`. An account that never followed gets one
  sentence and the button. One that did gets how many of the ranking's stocks it holds, its return since the first
  follow beside the benchmark's over the same sessions, the stocks it lacks and the holdings that left. The button
  asks first, listing every sale and purchase, and leaves once the account holds the ranking. The block is under
  `['owner', 'run-results']`, and polls while the server says a run of the user runs. The window and price wording is
  the follow panel's (`runs:follow.*`).

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

The mock account page (`/account`) is the mock account alone. The SinoPac account has its own page
(`/account/sinopac`, `BrokerageAccountPage.tsx`), for a user with `use_real_broker`, and it only reads:

- Its first card says which server the figures come from ("Simulation server, no real money" or "Real account") and
  whether the site may order there, before any figure and whatever else the page shows. It says once that every
  figure is the broker's own, with the time read.
- While the site's login is down the server sends no statement: the page says so and that the site retries, and asks
  for nothing else. An `administrators_only` answer shows `AdministratorsOnly`, the state `RequireSignIn` shows.
- The statement reads in one order: the bank balance, market value and both P&Ls; the holdings at the broker's last
  prices; the settlements, each said as to pay or to receive, not by a market color; today's fills; the past sales;
  then the orders this site placed there, the same `TradesPanel` the mock account lists its trades with.

My holdings (`/holdings`) reads what the user holds as one portfolio. Its rules:

- It shows figures and scores and never an instruction: no wording, color or icon says what to do with a holding.
  `HoldingsPage.test.tsx` fails on such a word. Red and green stay on the gains and losses only.
- Every figure is the server's: the value at the last close held, the weights, the concentration, the share in the
  ranking's top, the weighted score. The page derives one thing, the unscored share, `1 - scored_share`.
- A holding is counted under its one source, so the same stock at the broker and entered by hand is two rows, each
  with its source's badge. The mock account's badge says it is play money.
- The sources to choose from are the `asked` of a first answer asked with no filter (`offeredSources`), as checkboxes
  in one order with the play money last; the last one stays checked. A choice of every source asks with no filter
  again (`sourcesToAsk`), so it reuses the first answer. A source asked and not read (`unreadSources`) is the
  brokerage while the site's SinoPac login is down, said once above the table.
- The score is the stock page's, from `shared/ui/ranking-score.tsx`: `RankingScore` as a card's content,
  `RankingScoreLine` in a row, `RankingScoreNote` for what it measures. Their wording is `common:score.*`. The score
  figures and the note leave where the server answers them null, which is a viewer the site hides the ranking from.
- A hand entry is a note, not an order. Its stock is chosen through `StockPicker`, never typed; `parseEntry` checks
  the rest at the form with the contract's bounds; the server's refusals (an unlisted stock, the listing unavailable)
  show at the form. A change opens the same form on the entry with its stock fixed, and a removal asks first.
- A watched stock is not a holding. The route hands the watchlist's stocks in only where the site shows the
  watchlist, and the page offers the ones with no entry; choosing one opens the form on that stock.
- A table row carries on a phone what its hidden columns said: the source and the shares at their cost, the value and
  the weight, the close with its date and the revenue reading, then the score.

`shared/ui/` holds vendored shadcn/ui sources and the project's own primitives (`panel`, `data-table`, `stat`,
`segmented`, `range-tabs`, `show-more`, `range-meter`, `breadth-bar`, `quote-headline`, `state-block`, `page-header`,
`technical-strategy-note`, `ranking-score`, `error-state`,
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
every page at 360, 768 and 1440 px in both themes, with an audit of each (sideways scroll, controls under 44 px
on a phone, text cut off, page errors) in `audit.json`.

CI runs the first four in `.github/workflows/frontend.yml`, and the root `just frontend-check` runs them locally.
E2E needs a real backend, so it runs only on your machine. [README.md](../README.md#browser-flows-e2e) says how and why.
