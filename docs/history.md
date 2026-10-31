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
