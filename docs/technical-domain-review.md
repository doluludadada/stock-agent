# Technical analysis domain review

This review answers the question under US-001 in `docs/requirements.md`. Are the technical-analysis domain models split too finely? And where does the technical-scoring configuration belong, `appsetting.yaml` or the strategy file?

It covers `a_domain/rules/technical/` (`criteria/`, `calculation/`, `strategy.py`), `a_domain/model/analysis/`, `a_domain/model/indicators/`, and `RuleEffect` in `a_domain/types/enums.py`. Paths below are relative to `backend/src/` unless they start with `config/` or `docs/`.

## The criteria are not split too finely

Each criterion is one frozen dataclass with a `name` and an `apply(stock) -> bool`. There are 17 configurable criteria in 8 files under `rules/technical/criteria/`, grouped as momentum, trend, volatility and volume.

That grain is right for this system. Each criterion is one `type` in `config/technical.yaml`, one rule card in a future UI, and one name in a report's hard or soft failures. A coarser class, such as one `VolatilitySafetyCriterion` with optional daily-range and ATR checks, existed before `fbd500c`. It needed `None` branches for each check and produced one name for several conditions. The split removed those branches, and `docs/technical_settings_refactor_summary.md` asks to keep it.

The real cost was elsewhere. The same fact was written down two or three times:

- The rule type names existed as `TechnicalCriterionType` in the domain and again as the schema's tags.
- Each of the 17 rule schemas repeated its criterion's constructor call and its default values. One repeated default had drifted: an `int` default instead of the criterion's `float` changed report names from `RSI Range 0.0-80.0` to `RSI Range 0-80.0`.
- Which moving averages get calculated was known only by the calculator. Rules referenced MA periods without any check that those periods exist.
- `IntradayVolumeConfirmationCriterion` was a line-for-line copy of `VolumeExpansionCriterion`.
- `MacdBullishCriterion` has two flags that test the same thing. See [proposal 1](#proposals-not-applied).

## Changes applied in this branch

| Change | Why | Files |
| --- | --- | --- |
| Deleted `TechnicalCriterionType`. | Only the schema used it. The `type` tags now live once, as the `Literal` of each rule schema. | `a_domain/types/enums.py`, `c_infrastructure/technical/technical_settings_schema.py` |
| Replaced 17 hand-written `to_domain` methods with one in `BaseTechnicalRuleSchema`. Rule schemas read their defaults from the criteria. | A rule schema's fields are its criterion's constructor arguments by name. One conversion cannot drift, and the defaults have one source. | `technical_settings_schema.py` |
| Replaced `IndicatorOverridesSchema`, `ScoringOverridesSchema`, and the raw dataclass fields under `defaults` with `IndicatorParametersSchema` and `TechnicalScoringSchema`. Strategies inherit `defaults` before validation. | Pydantic built the domain dataclasses without running their icontract invariants. `rsi_period: 0` under `defaults` then crashed later with a `ViolationError` that names no field. Validation now sees the values a workflow uses and reports the field path. | `technical_settings_schema.py` |
| Added `IndicatorParameters.price_ma_periods` and `volume_ma_periods`. The calculator and the schema both use them. | A rule on a moving average the strategy does not calculate failed for every stock. Example: `price_above_ma` period 20 with `ma_mid: 10`. Loading now rejects that rule. | `model/indicators/indicator_parameters.py`, `rules/technical/calculation/calculator.py`, `technical_settings_schema.py` |
| Added invariants to `TechnicalSettings`. Strategy IDs are unique, and `active_strategy_id` and `buzz_strategy_id` name existing strategies. | Before, a missing ID failed only when a workflow asked for it. | `model/analysis/technical_settings.py` |
| Restored the `MovingAverages` invariants and deleted its unused `price()` and `volume()` methods. | `fbd500c` removed the invariants. Every other indicator model still has them. | `model/indicators/technical_indicators.py` |
| Deleted `IntradayVolumeConfirmationCriterion`. | It duplicated `VolumeExpansionCriterion`, and nothing used it. | `criteria/timing/` |
| Removed dead `None` checks and stale TODO markers, and documented each criterion. | `BollingerBands.percent_b` and `bandwidth` are never `None`. The Pylance warnings in `volume.py` and `volatility_safety.py` were already fixed. `basedpyright` reports no errors in either file. | `criteria/volume/volume.py`, `criteria/volatility/*.py`, `criteria/momentum/macd_bullish.py`, `criteria/timing/entry_timing.py` |

## Proposals not applied

These change report text, scores, or files outside the technical domain, so the owner decides.

1. **Delete `MacdBullishCriterion.require_histogram_positive`.** The calculator stores the histogram as `line - signal` (`calculation/formulas.py`, `latest_macd`). So "histogram > 0" and "line > signal" are the same check. In `config/technical.yaml`, the conservative `reduce_score_on_fail` MACD rule repeats a check that its `block_on_fail` MACD rule already makes. That rule can fail only for a stock that is already rejected. In moderate and aggressive, the histogram part of the soft MACD rule repeats the hard rule the same way. Deleting the flag changes two report names and raises the score of some already-rejected stocks by 5. I did not apply it because US-304 asks for parity with the pre-migration factory, which had the same redundancy.
2. **Decide what the timing criteria are for.** `criteria/timing/entry_timing.py` has five criteria (`PriceDropCriterion`, `GapCriterion`, `IntradayMomentumCriterion`, `IntradayRangeCriterion`, `ConsecutiveUpDaysCriterion`). No rule `type` maps to them, and the pre-migration factory never used them either. To use them for intraday entries (US-008), add one rule schema each to `technical_settings_schema.py`. Otherwise delete the folder.
3. **Put the threshold in every criterion name.** Reports identify a failure only by its name. `Daily Range Safety`, `Liquidity Check`, `Minimum Price Check`, `ATR Range`, and `Golden Cross` hide their thresholds, while `RSI Range 50.0-65.0` shows its own. This changes report text.
4. **Tie the history window to the indicator periods.** `analysis.lookback_days: 120` in `config/appsetting.yaml` returned 81 daily bars for 2330 in one CLI run on 2026-10-30. `GoldenCrossCriterion` needs `slow + 1` bars. Suppose a UI edit sets `ma_long: 90` and moves the MA_60 rules to period 90. That edit passes validation, and then every MA_90 rule fails for every stock. No load-time check can see the problem, because the two values live in different files. Derive the window from `IndicatorParameters` in `b_application/use_cases/collect/market_data_collector.py`, or validate the pair at startup.
5. **Delete `collect_rules.filter_min_price` and `filter_min_volume`.** No code reads them (`b_application/schemas/config.py`, `config/appsetting.yaml`). The `minimum_price` and `liquidity` rules in `config/technical.yaml` do that job.
6. **Confirm the liquidity unit.** Yahoo reports volume in shares (`c_infrastructure/market/yahoo_finance_adapter.py`). `min_daily_volume: 500` is 500 shares, half of one 1,000-share lot. I expect it to reject almost no listed stock (inferred, not measured). If the intent was 500 lots, the value is 500,000.

`TechnicalStrategy` lives in `rules/technical/strategy.py`: a strategy evaluates stocks in its one `apply` method, so it belongs with the rules. The values it is built from are models: `TechnicalRule` and `TechnicalScoring` in `model/analysis/`, `IndicatorParameters` in `model/indicators/`. `TechnicalSettings` lives in `model/analysis/` and only selects strategies.

## Where technical-scoring configuration belongs

All technical-scoring configuration belongs in `config/technical.yaml`. `config/strategies.yaml` no longer exists.

- `config/technical.yaml` is the tracked template. It holds everything that decides `technical_score` and the technical pass or fail: indicator periods, scoring points, rules with their `effect`, and which strategy each workflow uses (`active_strategy_id`, `buzz_strategy_id`). Nothing writes to it, so its comments stay.
- `config/technical.local.yaml` holds saved edits. `YamlTechnicalSettingsRepository.save` writes it, and `load` prefers it at every workflow start. Git ignores it. To reset to the template, delete it.
- `config/appsetting.yaml` holds what happens after the technical score. Examples are `technical_weight` and `ai_weight` for the composite score, the buy and sell thresholds, risk sizing, and providers. `analysis.lookback_days` is the one setting there that limits technical results. See proposal 4.

The requirement line in US-304, "`strategies.yaml` remains the source of truth until the UI persistence layer is implemented", is out of date. `config/technical.yaml` is the source, and saved values go to `config/technical.local.yaml`.
