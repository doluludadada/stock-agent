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
