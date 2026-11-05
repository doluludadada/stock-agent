---
## US-007 — Social Buzz Filtering

* Added `buzz_min_mentions`.
* Renamed PTT-specific threshold to `buzz_min_engagement`.
* `SocialBuzzCriteria.is_trending()` now filters Buzz candidates.
* Buzz passes when either:

  * `mention_count >= min_mentions`
  * `engagement >= min_engagement`
* `PttProvider` stores provider metrics in `Article.raw_metadata`.
* PTT engagement = `push + boo + arrow`.
* `BuzzScanner` aggregates articles by `stock_id`.
* Stocks below both Buzz thresholds stop before US-006 analysis.
* Added stats:

  * `buzz_scanned`
  * `buzz_qualified`
* `Article` received comments only; no new engagement field.
* `ISocialMediaProvider` still owns fetch + archive save.
* `PttProvider` and `PttParser` remain in the same file.
* Sentiment, LLM, and model training are excluded from US-007.
* Future social sources should normalize source-specific activity into generic `engagement`.
* US-007: code complete; verification pending.

---

---

## 2026-10-31 Requirements completed and the code brought in line with the architecture guide

* Branch `feat/complete-requirements`, from `develop` at `9052216`. Not merged into `develop`.
* Every acceptance criterion now has evidence in `docs/requirements-status.md`: 229 by a passing test, 9 by a live drive, 2 replaced by owner rulings, 4 partial with the reason.
* The code follows `docs/clean_architecture_guide.md`. `backend/tools/architecture_check.py src --pyright` reports 0 findings and 0 pyright errors.
* One `Pipeline` in `b_application/pipeline.py` holds every workflow, and one composition root, `d_presentation/dependencies.py`, wires the CLI and the Web API.
* Each domain rule makes one decision in `apply`, and each use case has one `execute`. Every adapter method is an `@override` of its port.
* The order steps run one decision at a time: `OrderPreparation` gates and records the order, `OrderExecution` sends it, and `OrderOutcome` records the broker's answer.
* Settings live in `config/appsetting.yaml`, including every outside URL, timeout and page limit. The news and PTT clients verify server certificates.
* The CLI uses one menu table, menu 7 warns about positions with no live quote, and the database carries a schema version stamp. Startup refuses any other version.
* A review against the guide moved what the checker cannot see:
  * Buzz, Intraday and manual BUY share the public `Pipeline.send_orders` workflow.
  * The skip reasons are a `SkipReason` `StrEnum`, and one `OrderAcceptanceRule` holds the order policy both brokers applied.
  * `AccountHistoryReport` is an application schema, and the menu 5 and 6 views decide nothing.
  * The 13 settings whose code default disagreed with the YAML, and every other setting in their sections, now live only in the YAML. 40 fields still keep a default equal to the YAML value, and a test fails when one of them drifts.
  * Two new checker rules keep the CLI and the Web API from deciding anything, and strategies are built only from the technical settings.
* The owner ruled on 2026-10-31:
  * The Shioaji odd-lot part goes ROD and is cancelled when it is still working after the polls.
  * A BUY risks `risk_per_trade_pct` of the account's equity, which is fixed once per run.
  * Bond ETFs pay no transaction tax through `market.bond_etf_tax_exempt_until` (2026-12-31).
  * Report prompts ask the AI for English.
  * US-005 replaces US-003's survivors-only watchlist rule.
  * Intraday still analyses held positions that failed the technical filter.
* Verification on d931761:
  * 821 tests pass, and the architecture check reports 0 findings and 0 pyright errors.
  * The order-gate model check passes all seven properties at default bounds (1 stock, 18 configs, 475,731 runs) and with 2 stocks on the shipped config (11,948,412 runs), and all 16 mutants are caught.
  * CLI and Web API drives ran on 2026-10-31 and 2026-11-01 with the market closed. The menu 5 and 6 AI explanations are English.
* Still open:
  * A live intraday fill on a weekday between 09:00 and 13:25.
  * A Shioaji login against a real account.
  * The odd-lot wait against TWSE's matching interval.
  * The size of an equity-based BUY.
  * A run record lost under a concurrent database reader.
  * A native crash at pytest exit.

## 2026-11-02 The code rebuilt to the rewritten architecture guide

* On `develop`, from `dc42d6e`. The guide was rewritten first (one concept per file, one model style, constants in `enums.py` or settings, one Pipeline of use cases) from the owner's review notes in the code, and `AGENTS.md` became the one project rule file that Codex and Claude Code share.
* The domain:
  * Every model and rule is a pydantic dataclass. icontract and SQLModel left the domain; SQLModel is only for infrastructure tables.
  * Split files went back to one file per concept: the account (`Account`, `Position`, and the account value shapes, five down to three), the order (its life cycle on `OrderStatus`), the watchlist, the technical indicators, the strategy, EPS, and the P/E valuation and scan.
  * Decisions left the models for rules: the order acceptance check, the fill snapshot marks, the filing deadlines and finality, the P/E appraisal, the valuation scan step.
  * Module constants became enum labels or settings: the filing deadlines and grace, the report sentences, the prompt rules.
* The application:
  * One `Pipeline` whose fields are use cases. The five step-group classes are gone, presentation calls only the Pipeline, and no use case sees `PipelineStatus`: each takes values and `stats` and returns its result.
  * `AccountEquity`, `AnalysisCandidates`, `DecisionCandidates`, `CompositeScorer`, `ContextLoader` and `AiProcessor` were folded into the steps that need them. `StrategyLoader` and `ChatReply` are new.
* The checker gained FUTURE-IMPORT, DOMAIN-STYLE, MODULE-CONSTANT, PIPELINE-FIELDS, RULE-CALLERS, USECASE-STATUS and PATH-COMMENT, and pyright reports deprecations.
* Visible changes: `GET /v1/account/history` returns flat positions and an equity curve keyed by date; menus 5 and 6 print one-line refusals; a manual BUY of a stock with no composite score reads the account and the quote before it refuses.
* Verification:
  * 840 tests pass, and the architecture check reports 0 findings and 0 pyright errors.
  * The order-gate check passes all seven properties at default bounds (542,394 runs) and with 2 stocks (15,132,225 runs), and all 17 mutants are caught. A run-by-run trace comparison of the old and new code found 472,734 identical runs.
  * Menus 1 to 7, the Web API and the settings page were driven with the market closed.
* Still open:
  * `_send_orders` is a loop in the Pipeline; the guide's shape is one use case that owns the one-order-per-decision rule.
  * The technical settings repeat their limits in the infrastructure schema, because moving them changes where the settings page shows an error.
  * `ValuationAppraiser` and `ValuationScreener` each wrap one rule call, and the Pipeline calls `ValuationScan.after_technical_step`.
  * The MOPS industry feeds list only companies that filed the newest quarter, so most industries are missing early in each filing season.
  * A chat reset deletes the system prompt (chat is future work).

## 2026-11-03 Technical strategies became formulas the user composes

* On `develop`, from the half-finished working tree of `1c256b7`, following `docs/strategy-implementation-handoff-2026-11-03.zh-TW.md`. The design is `docs/technical-strategy-formulas.md`.
* The domain:
  * A rule's condition is a formula of typed parts: a number, a daily bar field, the latest price, an indicator output, arithmetic, a comparison (crossings included) and `all`/`any` groups. Indicators have stable ids such as `ind_a` and parameters the user sets. The criteria classes, the dotted series names and `TechnicalIndicators` are gone.
  * Missing data, a division by zero or a non-finite value fails the stock with score 0 instead of making a comparison false. `required_bars` reaches the history fetch.
* Storage: each owner's settings are rows of five SQL tables with composite foreign keys and CHECK constraints, saved with a revision check. `config/technical.yaml` became `config/strategies/{conservative,balanced,aggressive}.json`, which score 300 seeded stocks exactly as the criteria did. Buzz now starts on Balanced.
* Entry points: `GET`/`PUT /v1/technical-settings` (token, 409, 422), `GET /v1/technical-settings/built-in-strategies` and `/schema`; the settings page and `/reset` are gone. CLI menu 8 loads a built-in strategy for the session.
* The order step is an inline loop in Buzz, Intraday and manual BUY instead of `Pipeline._send_orders`. The guide now exempts Pipeline operations from the length limit, lets a rule expose derived properties, and lets the Pipeline and presentation name a rule's value type in an annotation.
* Settings: `db` holds the database only, the chat reset strings moved to `chat`, `technical` holds the owner, the built-in strategy list and the initial choice. The AI provider is Claude Haiku 5.5 (`claude-haiku-5-5`); NVIDIA is configured but its model did not answer.
