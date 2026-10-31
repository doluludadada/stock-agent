# TW Stock Alpha Agent

Application for Taiwan stock screening, report generation, watchlist management, and mock trade execution.

The current primary interface is the CLI. It scans Taiwan stocks, finds social buzz, runs technical and AI analysis, builds watchlists, and can submit orders through the currently wired mock execution provider.

This project is not financial advice. Treat generated signals as decision support.

## Current Status

- Market: Taiwan stocks.
- Primary UI: CLI at `backend/src/d_presentation/cli/interactive.py`.
- API: FastAPI at `backend/main.py` starts Full Cycle and specific-stock analysis, reads runs, signals, orders, the watchlist and the account, and edits the technical settings (page at `/ui/settings`). It never orders. See [Web API](#web-api).
- Order execution: `MockExecutionProvider` by default. `ShioajiExecutionProvider` (Sinopac) is wired for `execution_provider: shioaji`, see [Real broker (Shioaji)](#real-broker-shioaji). It has not been run against a real Shioaji account.
- Database: local SQLite at `stock_agent.db` unless PostgreSQL credentials are provided.
- Knowledge store: ChromaDB path is configured by `config/appsetting.yaml`.

## CLI Workflows

Run the CLI from the repository root:

```powershell
just cli
```

Or run it directly:

```powershell
cd backend
uv sync --all-extras
$env:PYTHONPATH = "src"
uv run python -m d_presentation.cli.interactive
```

Menu behavior:

| Option | Workflow | What it does | Orders |
| --- | --- | --- | --- |
| 1 | Run Full Cycle | Scans the full market, builds a `TECHNICAL` watchlist, runs news and AI analysis, generates next-session signals. | Never submits orders. |
| 2 | Scan Social Buzz | Finds discussed stocks, enriches market data, keeps technical survivors as `BUZZ`, analyses them, generates signals. | Submits only if market and order checks allow. |
| 3 | Run Intraday Trading | Loads held positions and active watchlist, refreshes market data, revalidates technicals and AI, generates signals. | Submits only if market and order checks allow. |
| 4 | Analyse Specific Stocks | Loads the requested stock IDs and runs the technical filter, news and AI on every one of them, a technical failure included, then offers them all for the `MANUAL` watchlist. | No automatic order. Manual BUY override requires confirmation. |
| 5 | Value Specific Stocks | Shows TTM EPS from MOPS filings, the exchange's official close and the current P/E, asks a target P/E, then prints three fair-price scenarios and an AI explanation built from those numbers. | Never. No watchlist write either. |
| 6 | Scan Undervalued Stocks | Screens every listed and OTC stock at a target P/E and minimum undervaluation, optionally confirms the matches with the active technical strategy, and can ask the AI to explain the top matches. | Never. No watchlist write either. |
| 7 | Account History | Shows cash, positions with unrealized PnL at the latest quote, the equity curve since the first fill, and the account as of a date you enter. Warns about each position with no live quote, which is then priced at its last daily close, or at its average cost when no price came back. | Never submits orders. |

Every BUY or SELL decision ends as one row in the `orders` table with its run id and decision id: REJECTED with the reason when a gate refuses it (order mode, market closed, a quote older than `freshness.realtime_max_lag_minutes`). IOC orders trade only in continuous trading, 09:00 to 13:25 on weekdays; the opening call auction (08:30-09:00) and the closing call auction (13:25-13:30) take ROD only, so an order then is REJECTED as `MARKET_CLOSED`, otherwise what the broker did with it, including the fee, the tax and, for a SELL, the realized PnL. Orders are LIMIT at the decision's price and IOC. The limit is a valid exchange tick (`LimitPriceRule`, with the TWSE/TPEx tick table in `market.stock_ticks` and `market.etf_ticks`): a quote off the tick grid rounds up for a BUY and down for a SELL, and sizing prices a BUY at that limit. One run decides best composite score first, a tie going to the lower stock id, and sizes each BUY against the cash the run's earlier BUYs left, their fees included, so a run never commits more than the account's cash; when it runs out, the lower-scored stocks get HOLD. Fees and tax come from `market` in `config/appsetting.yaml`: a SELL pays the transaction tax `tax_rate` (0.3%) on a stock and `etf_tax_rate` (0.1%) on an ETF, which is a code starting with `00`.

### Specific Stock Flow

When you enter a stock such as `2330`, the app should only research that stock:

1. Load the stock from the stock provider.
2. Fetch OHLCV data and calculate indicators.
3. Run the technical filter.
4. Run news and AI analysis on the stock even when the technical filter failed it, so you see the whole report.
5. Show the stock report.
6. Offer the stock for the `MANUAL` watchlist.

Adding the stock to the watchlist is a separate manual confirmation. A manual BUY override is also separate. It is sized with fees included and still goes through the same order steps, which check the order mode, market-open status and the age of the quote. The CLI prints the order's status and reason, or why no order could be built.

## What Counts As "Good"

The project currently treats a stock as worth acting on only after multiple gates:

1. Technical filter has no hard failure.
2. News and AI analysis produce an acceptable report.
3. Combined score passes configured thresholds.
4. Account risk checks do not block the stock.
5. Order execution is allowed by the market clock.
6. Quantity and mock account constraints are valid.

Main thresholds live in `config/appsetting.yaml`:

```yaml
analysis:
  technical_weight: 0.5
  ai_weight: 0.5
  min_combined_score_buy: 80
  max_combined_score_sell: 30
```

The technical strategies and which one each workflow uses (`active_strategy_id`, `buzz_strategy_id`) live in `config/technical.yaml`. That file is the template: the settings page and `PUT /v1/technical-settings` save to `config/technical.local.yaml` next to it, which wins while it exists, and deleting it resets to the template.

## Watchlist Types

`WatchlistType` is the source of truth for why a stock is on the watchlist:

| Type | Meaning |
| --- | --- |
| `TECHNICAL` | Passed the full-market technical scan. Stays active through the close of the `watchlist.automatic_expiry_sessions`-th (1) trading session that opens after Full Cycle last selected it, so Friday evening's entries last through Monday's session. |
| `BUZZ` | Came from social buzz and passed technical filtering. Expires like `TECHNICAL`, counted from the last Buzz scan that selected it. |
| `MANUAL` | User reviewed a specific-stock report and manually added it. Never expires. |

A stock has one `watchlists` row per type, so it can be `TECHNICAL`, `BUZZ` and `MANUAL` at once. `WatchlistRule` renews an automatic row each time its workflow selects the stock again and never changes a `MANUAL` row. Adding a stock that is already on the manual watchlist prints `Already present on manual watchlist`.

## Application Flow

```mermaid
flowchart TD
    CLI[CLI Menu] --> WF[Pipeline]

    WF --> FULL[Run Full Cycle]
    WF --> BUZZ[Scan Social Buzz]
    WF --> DAY[Run Intraday Trading]
    WF --> ONE[Analyse Specific Stocks]

    FULL --> MS1[MarketScanner: universe, MarketDataCollector: daily OHLCV]
    BUZZ --> BS[BuzzScanner: social candidates]
    BUZZ --> MS2[MarketDataCollector: candidate daily OHLCV]
    DAY --> LOAD[IntradayCandidates: held positions + active watchlist]
    LOAD --> MS3[RealtimeQuoteFeed + MarketDataCollector: quotes and daily OHLCV]
    ONE --> STOCK[StockLookup: requested stock IDs]
    STOCK --> MS4[MarketDataCollector: requested daily OHLCV]

    MS1 --> TF1[TechnicalFilter -> TECHNICAL watchlist]
    MS2 --> TF2[TechnicalFilter -> BUZZ watchlist]
    MS3 --> TF3[TechnicalFilter]
    MS4 --> TF4[TechnicalFilter -> MANUAL candidates]

    TF1 --> AP[NewsFeed + AiAnalyser + CompositeScorer]
    TF2 --> AP
    TF3 --> AP
    TF4 --> AP

    AP --> SIG[Signals when generated]
    SIG --> REP[Reporting]

    FULL --> NOORDER[No order execution]
    BUZZ --> ORDERABLE[Order path allowed]
    DAY --> ORDERABLE
    ONE --> MANUAL[Manual confirmation only]
    MANUAL --> ORDERABLE
    ORDERABLE --> PREP[OrderPreparation: gates and records the order]
    PREP --> ORDER[OrderExecution: sends it]
    ORDER --> MOCK[MockExecutionProvider]
    MOCK --> OUT[OrderOutcome: takes the result into the run]
```

Important distinction:

- `NewsFeed`, `AiAnalyser` and `CompositeScorer` only gather news, ask the AI and combine the scores.
- `Pipeline` (`backend/src/b_application/pipeline.py`) holds every workflow as one method. Each method lists the use cases it runs, so it alone decides whether signals, reporting, watchlist writes or order steps happen.
- The order steps run one decision at a time: `OrderPreparation` checks the order mode, the trading phase and the quote's age and records the order, `OrderExecution` sends it to the broker, and `OrderOutcome` records what the broker did.
- `MarketScanner` loads the universe, `StockLookup` the requested stock IDs and `IntradayCandidates` the held and watched stocks. `MarketDataCollector` loads daily OHLCV, `RealtimeQuoteFeed` loads the realtime quotes that price orders, and `TechnicalFilter` calculates the strategy's indicators and applies its rules.

## Architecture

The code follows the existing Clean Architecture split:

| Layer | Path | Responsibility |
| --- | --- | --- |
| Domain | `backend/src/a_domain` | Models, ports, enums, pure rules. No application, infrastructure, or presentation imports. |
| Application | `backend/src/b_application` | Use cases, the one `Pipeline` with every workflow, the pipeline status, and the settings classes in `b_application/config/`. |
| Infrastructure | `backend/src/c_infrastructure` | Database, market data, AI adapters, feed providers, LINE platform, mock trading. |
| Presentation | `backend/src/d_presentation` | CLI, Web API, the one composition root both use (`dependencies.py`). |

Application use cases coordinate work. Domain rules own business decisions. Infrastructure implements ports.

## Configuration

Main files:

| File | Purpose |
| --- | --- |
| `config/appsetting.yaml` | Active model, logging, analysis weights, thresholds, folders, mock account, indicator periods, and under `sources` every outside endpoint (TWSE, TPEX, MOPS, PTT, news, AI, LINE) with the text formats their pages use, their timeouts and how much of each page is read. The settings classes are in `backend/src/b_application/config/`. |
| `config/technical.yaml` | The technical strategies, their indicator parameters and rules, and `active_strategy_id` and `buzz_strategy_id`. Saved edits go to `config/technical.local.yaml`. |
| `config/instructions.yaml` | AI report prompts and RAG injection prompts. |
| `.env` | API keys, optional database credentials and the Shioaji credentials. |

### Real broker (Shioaji)

The shipped settings use the mock broker in `mock_only` order mode. The CLI and the Web API refuse to start a combination that could send an order nobody meant to send, and says what to change:

| `environment` | `execution_provider` | `order_mode` | Starts? |
| --- | --- | --- | --- |
| any | `mock` | `mock_only` or `disabled` | Yes. |
| any | `mock` | `live` | No. Live order mode needs Shioaji. |
| `dev` | `shioaji` | any | No. DEV never touches a real broker. |
| `test` or `live` | `shioaji` | `mock_only` | No. Use `disabled` to read the Shioaji account without ordering. |
| `test` or `live` | `shioaji` | `disabled` | Yes. Cash and positions come from Shioaji, no order is sent. |
| `test` | `shioaji` | `live` | No. Live order mode needs `environment: live`. |
| `live` | `shioaji` | `live` | Yes. Menus 2 and 3 and a confirmed manual BUY send orders to Shioaji. |

`shioaji.simulation: true` (the default) logs in to Shioaji's paper-trading environment. Set it to `false` only after testing there; the account is then real money. Shioaji needs `SHIOAJI_API_KEY` and `SHIOAJI_SECRET_KEY` in the environment or `.env`, and in production also `SHIOAJI_CA_PATH`, `SHIOAJI_CA_PASSWORD` and `SHIOAJI_PERSON_ID`. With any non-mock broker the menu header shows a red REAL BROKER panel with the broker, simulation or production, and the order mode.

How the adapter trades: quantities are shares; whole 1000-share lots go as one board-lot order and the rest as one intraday odd-lot order, both LIMIT IOC. Before sending, it refuses a BUY that the cash cannot pay, because the broker checks the trading limit, not the cash. Cash is the bank balance minus settlement payments due and minus the BUYs the broker lists as dealt today. An order still working after a few seconds is cancelled; one the broker still reports as working, or a timed-out call it cannot find again, ends FAILED with a reason that says to check the broker.

Environment variables are loaded from `.env` or `../.env` relative to the backend process. Common keys:

```env
OPENAI_API_KEY=
GROK_API_KEY=
GEMINI_API_KEY=
GROQ_API_KEY=
TAVILY_API_KEY=
LINE_CHANNEL_ID=
LINE_CHANNEL_SECRET=
LINE_CHANNEL_ACCESS_TOKEN=
API_TOKEN=
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=
DB_NAME=
```

If PostgreSQL credentials are missing, the app uses local SQLite.

## Development Commands

From `backend`:

```powershell
uv sync --all-extras
$env:PYTHONPATH = "src"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run python tools/architecture_check.py src --pyright
```

`tools/architecture_check.py` checks the rules of `docs/clean_architecture_guide.md` (layer direction, one `apply` per domain rule, one `execute` per use case, `@override` on every adapter method, function length and complexity, no hard-coded URLs) and, with `--pyright`, counts pyright errors. It prints a count per rule and must end at `TOTAL 0`.

Run the API:

```powershell
cd backend
$env:PYTHONPATH = "src"
$env:API_TOKEN = "<a long random string>"
uv run uvicorn main:app --host 0.0.0.0 --port 8800 --reload
```

Run Docker:

```powershell
docker compose up --build
```

## Web API

The API runs on the same runtime as the CLI: `backend/src/d_presentation/dependencies.py` builds it once at startup, with the same trading-setup checks, so the API refuses to start on any setup the CLI refuses. The OpenAPI page is at `/docs`.

No endpoint places, cancels or modifies an order. The API starts only Full Cycle and specific-stock analysis, which never reach order execution, and it has no manual BUY.

| Method and path | What it does |
| --- | --- |
| `POST /v1/runs/full-cycle` | Starts menu 1 in the background. Answers 202 with the run id. |
| `POST /v1/runs/specific-stocks` | Starts menu 4's analysis of `stock_ids` in the background. Each stock is one AI call. |
| `GET /v1/runs`, `GET /v1/runs/{run_id}` | Run state (`running`, `finished`, `failed`, `unfinished`) and the run record. A specific-stock run also lists each stock's report while the server runs. |
| `GET /v1/runs/{run_id}/signals`, `.../orders` | The run's decisions and orders, with run id, decision id, status, reason, fee, tax and realized PnL. |
| `GET /v1/watchlist`, `POST /v1/watchlist/manual` | Active entries with type and expiry; add listed stocks to the MANUAL watchlist. |
| `GET`/`PUT /v1/technical-settings`, `POST /v1/technical-settings/reset`, `GET /v1/technical-settings/schema` | Read, save and reset the technical settings. The next workflow uses the saved ones. |
| `GET /v1/account/history?as_of=YYYY-MM-DD` | Menu 7. `live_stock_ids` lists the held stocks marked at a realtime quote. |
| `GET /ui/settings` | A page that edits each strategy's indicator parameters through the endpoints above. |

One workflow runs at a time; a second start answers 409. Every write needs `Authorization: Bearer <API_TOKEN>` and `"confirm": true` in the JSON body: 403 while `API_TOKEN` is unset, 401 without the token, 422 without the confirmation. Reads need no token, so do not expose the port beyond a network you trust.

## Data Written Locally

- `stock_agent.db`: SQLite application and mock trading state. The trading record is `workflow_runs`, `trade_signals`, `orders` and `account_snapshots`; the mock broker's book is `mock_cash` and `mock_positions`.

Tables are created with `create_all`, which never changes an existing table. A new database also gets a `schema_version` row, the code's `SCHEMA_VERSION` (`backend/src/c_infrastructure/database/models/schema_version_dto.py`), which says how its rows are stored. At startup the app stops, changing nothing, when the database is not new and its schema version is missing or another one, or when an existing table's columns differ from the code. The message names each table to drop. A `stock_agent.db` made before the schema version existed is refused for every table, because several of its tables hold Taiwan wall-clock times that the current code reads as UTC. Delete that file, or drop the tables the message names; the next start recreates them empty. Cached prices and EPS refill themselves, while the mock account, watchlist and trading rows in a dropped table are lost. Such a file's `mock_positions` also hold average costs without the buy fee, and its unused `mock_orders` table can be dropped.
- `chroma_data/`: Chroma persistence.
- `news_archive/`: archived news payloads.
- `buzz_archive/`: archived social buzz payloads.
- `ai_responses/`: saved AI outputs.

## Safety Rules

- Every BUY or SELL decision gets one `orders` row before anything reaches the broker. A closed market, a disabled order mode or a quote older than `freshness.realtime_max_lag_minutes` makes that row `REJECTED` with the reason, and nothing is sent.
- `Run Full Cycle` does not call order execution.
- The Web API never orders: it starts only Full Cycle and specific-stock analysis, and every write needs `API_TOKEN` and `confirm: true`.
- Manual BUY override is explicit user intent and still uses the same order checks.
- Real orders need `environment: live`, `execution_provider: shioaji`, `order_mode: live` and the Shioaji credentials together. Any other combination with Shioaji either refuses to start or only reads the account.

## Known Cleanup Areas

- Keep README, CLI text, workflow behavior, and tests aligned whenever a workflow changes.
