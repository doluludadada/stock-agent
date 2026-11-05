# Technical strategy formulas

This document describes the technical strategy design as it is implemented. It replaces the criteria classes, the
`config/technical.yaml` template and the YAML settings file. The proposals in
[`strategy-designer.md`](strategy-designer.md), [`technical_settings_refactor_summary.md`](technical_settings_refactor_summary.md)
and [`technical-domain-review.md`](technical-domain-review.md) are history where they disagree with it.

## What a user changes

A strategy is data: indicators with parameters, rules with formulas, and scoring numbers. A name is only a label.
Adding a rule, changing a period or a threshold, or composing a new formula from the parts below changes no Python.
Only a new indicator algorithm or a new operator needs code.

| Part | JSON | Meaning |
| --- | --- | --- |
| Number | `1.8` | A finite constant. A string or a boolean is refused. |
| Market value | `{"type": "market", "field": "volume", "bars_ago": 1}` | A field of a completed daily bar: `open`, `high`, `low`, `close`, `volume` (shares). `bars_ago` counts trading days back from the latest bar. |
| Latest price | `{"type": "latest_price"}` | The realtime quote when the run has one, else the latest daily close. It has no earlier sample, so a crossing cannot read it. |
| Indicator value | `{"type": "indicator", "indicator_id": "ind_c", "output": "value", "bars_ago": 1}` | One output of one of the strategy's indicators. The kind decides which outputs exist (`IndicatorKind.outputs`). |
| Arithmetic | `{"type": "arithmetic", "operator": "multiply", "left": ..., "right": 1.8}` | `add`, `subtract`, `multiply`, `divide`. Either side may be another part. |
| Comparison | `{"type": "comparison", "operator": "crosses_above", "left": ..., "right": ...}` | `gt`, `gte`, `lt`, `lte`, `eq`, `ne`, `crosses_above`, `crosses_below`. A crossing holds only on the bar where it happens: the left side was at or below the right side one bar earlier and is above it now. Both sides are evaluated whole at both bars. |
| Group | `{"type": "group", "operator": "all", "conditions": [...]}` | `all` or `any` of conditions, which may be groups. |

An indicator has a stable id that never holds a parameter, such as `ind_a`, and its parameters:
`{"kind": "sma", "period": 37}`. Changing `ind_a`'s period changes every rule that reads `ind_a`; a rule that needs
another period reads another indicator. Two MACD indicators with different parameters stay separate, and one MACD's
line and signal are outputs of one id.

Example, "SMA 37 crosses above SMA 83 and today's volume is above 1.8 times the 25-day average volume before today":

```json
{
  "indicators": {"ind_a": {"kind": "sma", "period": 37}, "ind_b": {"kind": "sma", "period": 83}, "ind_c": {"kind": "volume_sma", "period": 25}},
  "rules": [{
    "name": "My trend and volume rule",
    "effect": "block_on_fail",
    "condition": {"type": "group", "operator": "all", "conditions": [
      {"type": "comparison", "operator": "crosses_above",
       "left": {"type": "indicator", "indicator_id": "ind_a"}, "right": {"type": "indicator", "indicator_id": "ind_b"}},
      {"type": "comparison", "operator": "gt", "left": {"type": "market", "field": "volume"},
       "right": {"type": "arithmetic", "operator": "multiply",
                 "left": {"type": "indicator", "indicator_id": "ind_c", "bars_ago": 1}, "right": 1.8}}
    ]}
  }]
}
```

## Evaluation

- `TechnicalStrategy.required_bars` is the most any reference needs: an indicator's own history plus its `bars_ago`,
  plus one bar for a crossing. The SMA 83 crossing above needs 84 bars. The Pipeline passes it to
  `MarketDataCollector`, which fetches `max(lookback_days, required_bars x history_calendar_days_per_bar)` calendar
  days. The window is an estimate; a stock with fewer bars than required fails with score 0.
- Each indicator output a rule reads is computed once per stock and `bars_ago` from the bars before that point.
- A missing output, a division by zero or a result that is not finite makes the rule unavailable, never a zero or a
  `False`. A group evaluates all its parts before it answers. One unavailable rule fails the stock with score 0 and
  the hard failure `Technical data unavailable: <rule names>`.
- Each rule's effect applies once: a failed `block_on_fail` rule rejects the stock and costs
  `block_failure_penalty`, a failed `reduce_score_on_fail` rule costs `failure_score_reduction`, a passed
  `increase_score_on_pass` rule adds `pass_score_increase`. The score is clamped to 0..100.

The code is `backend/src/a_domain/rules/technical/formula.py` (parts and evaluation),
`calculation/calculator.py` (indicator parameters and outputs) and `strategy.py` (rules, scoring, settings).

## Built-in strategies

`config/strategies/conservative.json`, `balanced.json` and `aggressive.json` each read on their own. They keep the
thresholds and effects of the criteria classes they replaced: a seeded test scores 300 random stocks with HEAD's
criteria and with the formulas and finds every score, pass, failure count and bonus equal
(`backend/tests/test_built_in_strategies_regression.py`). Two rules changed form, not result: the Golden Cross margin is
`(SMA20 - SMA60) / SMA60 < 0.03`, as the criterion computed it, and the daily range is `(high - low) / low`.

Behavior that did change, by requirement:

- A stock with fewer than 61 daily bars now fails the built-in strategies with score 0. The criteria scored the rules
  they could.
- Buzz uses the owner's `buzz_strategy_id`, which starts as `balanced`. HEAD's `buzz_safety_only` and other extra
  strategies are not built in.

## Storage

Settings are rows in five tables, all keyed by owner (`backend/src/c_infrastructure/database/models/technical_settings_dto.py`):

| Table | Rows |
| --- | --- |
| `technical_settings` | One per owner: `active_strategy_id`, `buzz_strategy_id`, `revision`. |
| `technical_strategies` | The owner's strategies: name, position, scoring numbers. |
| `technical_indicators` | Each strategy's indicators: id, kind and the parameter columns of that kind. |
| `technical_rules` | Each strategy's rules: position, name, effect. |
| `technical_formula_nodes` | One row per part of a rule's formula: position, parent position, node type, operator, constant, market field, indicator id, output, bars ago. |

Composite foreign keys keep every reference inside one owner and one strategy: a node can only name an indicator of
its own strategy. SQLite enforces foreign keys because the connector turns them on for each connection. One CHECK
constraint gives each rule one root node. A read builds each formula part from its row through the domain classes,
which validate every column, so a row whose columns do not fit its node type never loads as settings.

The first read for an owner saves an independent copy of every built-in strategy, with `technical.initial_strategy_id`
selected, in one transaction; a concurrent first read finds the row and reads it. A save carries the revision it read.
It updates the owner's row only when that revision is still current, replaces the owner's strategy rows, and
increments the revision, all in one transaction. A save from an older read raises `TechnicalSettingsConflictError`
and changes nothing.

`technical.owner_id` (`local`) names the one owner of this installation. The Web API's token is not an account: a
future service with sign-in takes the owner from the signed-in account, never from a client.

## Entry points

- Web API and the web UI's strategy library and designer: `GET`/`PUT /v1/technical-settings` (token required; 422 for invalid settings, 409 for a stale revision),
  and `GET /v1/technical-settings/built-in-strategies`. The OpenAPI document carries the JSON schema of a save, and
  `frontend/src/shared/api/indicator-outputs.json` the outputs of each indicator kind.
- CLI: menu 8 loads a built-in strategy for the runs of that CLI session. Saved settings and the Web API are unchanged.
- Each run loads its strategy once, before it starts; a save during a run applies to the next run.

## Not built yet

- An iOS editor. The web editor (`frontend/src/features/strategies`) is built on the API above: it reads the
  built-in strategies and the owner's settings, writes ordinary formulas (its quick fills included), describes each
  formula with a sentence generated from it, and saves with the revision it read (see `docs/web-integration.md`).
- Text formula input. A parser would build the same formula parts; nothing evaluates text.
- Sign-in and per-account owners. PostgreSQL is wired and selected by `db.backend: postgresql`, but this design has
  been run on SQLite only.
