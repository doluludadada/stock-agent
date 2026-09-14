# Technical Settings Refactor Summary

## Goal

Refactor technical-analysis configuration so the system supports:

- Single source of truth
- Hot reload without restart/rebuild/redeploy
- Future Web UI and iOS editing
- Future local SQLite settings
- PostgreSQL sync
- User-defined custom strategies
- Existing Clean Architecture / DDD structure
- Existing contract-based domain validation

---

## Final Architecture

```text
config/
└── technical.yaml

a_domain/
├── model/
│   └── analysis/
│       └── technical_settings.py
│
├── ports/
│   └── analysis/
│       └── technical_settings_repository.py
│
└── rules/
    └── technical/
        ├── strategy.py
        ├── calculation/
        └── criteria/

c_infrastructure/
└── technical/
    ├── technical_settings_schema.py
    └── yaml_technical_settings_repository.py
```

The existing `criteria/` and `calculation/` structure stays.

Only the strategy composition/configuration architecture changes.

---

## Source of Truth

### Development

```text
technical.yaml
    ↓
YamlTechnicalSettingsRepository
    ↓
TechnicalSettings
    ↓
Workflow
```

The repository reads the YAML file on every workflow start.

A workflow therefore gets the latest saved settings without restarting the application.

### Future local-first model

```text
technical.yaml
    ↓ default / reset

Local SQLite
    ↕ sync
PostgreSQL

SQLite
    ↓
TechnicalSettings
    ↓
Workflow
```

Rules:

- `technical.yaml` becomes the default/reset template.
- SQLite becomes the user's local runtime source of truth.
- PostgreSQL stores the synchronised copy for account/device sync.
- The analysis engine still runs on the user's device.
- Do not merge YAML + SQLite + PostgreSQL on every workflow.

---

## Hot Reload Definition

Hot reload means:

> The next workflow uses the latest saved technical settings without restart, rebuild, or redeploy.

Each workflow loads settings once:

```text
workflow starts
    ↓
repository.load()
    ↓
TechnicalSettings snapshot
    ↓
same snapshot used until workflow finishes
```

Settings must not change halfway through one workflow.

---

## TechnicalSettings

`TechnicalSettings` is a domain model, not a service.

Recommended shape:

```text
TechnicalSettings
├── active_strategy_id
├── buzz_strategy_id
└── strategies[]
```

Example:

```python
@dataclass(frozen=True)
class TechnicalSettings:
    active_strategy_id: str
    buzz_strategy_id: str
    strategies: tuple[TechnicalStrategy, ...]
```

`active_strategy_id` selects the normal/default strategy.

`buzz_strategy_id` selects the strategy used by the buzz workflow.

This avoids hard-coding a Python enum such as `BuiltInStrategyId.BUZZ`.

A future user can select:

```yaml
buzz_strategy_id: my_custom_momentum_strategy
```

without changing Python code.

---

## Important Correction: Do Not Add BuiltInStrategyId

This was an incorrect intermediate suggestion:

```python
strategy = settings.get_strategy(BuiltInStrategyId.BUZZ.value)
```

Do not introduce `BuiltInStrategyId`.

It conflicts with user-defined strategies.

Use:

```python
strategy = settings.buzz_strategy
```

instead.

---

## TechnicalStrategy

A strategy is the executable domain representation.

Recommended shape:

```text
TechnicalStrategy
├── strategy_id
├── indicators
├── scoring
└── rules[]
```

Example:

```python
@dataclass(frozen=True)
class TechnicalStrategy:
    strategy_id: str
    indicators: IndicatorParameters
    scoring: TechnicalScoring
    rules: tuple[TechnicalRule, ...]
```

---

## Indicator Settings

Indicator parameters describe how indicators are calculated.

Example:

```yaml
indicators:
  rsi_period: 14
  macd_fast: 12
  macd_slow: 26
  macd_signal: 9
```

Changing:

```text
RSI(14) → RSI(7)
```

means changing:

```yaml
rsi_period: 7
```

The next workflow recalculates RSI using period 7.

This is different from an RSI strategy rule such as:

```text
50 <= RSI <= 80
```

---

## TechnicalRule

Keep `TechnicalCriterion`.

Do not create another interface for `TechnicalRule`.

`TechnicalCriterion` already provides the polymorphic contract:

```python
class TechnicalCriterion(Protocol):
    @property
    def name(self) -> str: ...

    def apply(self, stock: Stock) -> bool: ...
```

`TechnicalRule` is only a domain value object:

```python
@dataclass(frozen=True)
class TechnicalRule:
    criterion: TechnicalCriterion
    effect: RuleEffect
```

Responsibilities:

```text
TechnicalCriterion
→ How is the condition evaluated?

TechnicalRule
→ What does that criterion mean inside this strategy?
```

Example:

```text
TechnicalRule
├── RsiRangeCriterion(50, 80)
└── BLOCK_ON_FAIL
```

The same criterion can be reused in another strategy:

```text
TechnicalRule
├── RsiRangeCriterion(50, 80)
└── REDUCE_SCORE_ON_FAIL
```

---

## RuleEffect

Final agreed enum:

```python
class RuleEffect(StrEnum):
    BLOCK_ON_FAIL = auto()
    REDUCE_SCORE_ON_FAIL = auto()
    INCREASE_SCORE_ON_PASS = auto()
```

This replaces the old three-list strategy structure:

```text
must_pass
should_pass
observe
```

Mapping:

```text
must_pass
→ BLOCK_ON_FAIL

should_pass
→ REDUCE_SCORE_ON_FAIL

observe
→ INCREASE_SCORE_ON_PASS
```

The new model is more explicit and easier to expose through Web/iOS UI.

---

## YAML Strategy Example

```yaml
active_strategy_id: moderate
buzz_strategy_id: buzz

strategies:
  moderate:
    rules:
      - type: rsi_range
        effect: block_on_fail
        min_rsi: 50
        max_rsi: 80

      - type: adx_trend
        effect: reduce_score_on_fail
        min_adx: 20
        max_adx: 50

      - type: golden_cross
        effect: increase_score_on_pass
```

Different strategies are different data, not different Python implementations.

Do not create:

```python
create_moderate_strategy()
create_buzz_strategy()
create_aggressive_strategy()
```

The goal is:

```text
N strategies
1 implementation
```

---

## Criterion Mapping

The selected approach is Pydantic discriminated unions in the infrastructure layer.

Example external data:

```yaml
- type: rsi_range
  effect: block_on_fail
  min_rsi: 50
  max_rsi: 80
```

Pydantic parses it into a typed document such as:

```python
RsiRangeRuleDocument
```

The infrastructure document converts itself into:

```python
TechnicalRule(
    criterion=RsiRangeCriterion(...),
    effect=RuleEffect.BLOCK_ON_FAIL,
)
```

This avoids:

- giant strategy factory
- `importlib`
- Python class names in YAML
- `dict[str, Any]`
- decorator registry magic
- large `if/elif` mapping methods

The explicit Pydantic union is acceptable even if it becomes long.

It is localised infrastructure complexity rather than domain complexity.

---

## Pydantic vs Contract Design

Keep both.

They solve different problems.

### Pydantic

Validates external/persisted data:

- YAML
- JSON
- SQLite payloads
- API payloads
- enum values
- required fields
- field types

### icontract

Validates domain/runtime invariants.

Example:

```python
@invariant(lambda self: 0 <= self.min_rsi <= self.max_rsi <= 100)
@dataclass(frozen=True)
class RsiRangeCriterion:
    ...
```

Do not remove existing contract-based design.

---

## Repository

Recommended interface:

```python
class ITechnicalSettingsRepository(Protocol):
    async def load(self) -> TechnicalSettings: ...

    async def save(self, settings: TechnicalSettings) -> None: ...
```

`load()` is required now.

`save()` is useful to support future Web/iOS/SQLite editing.

Do not add unrelated responsibilities such as:

```text
sync()
reload()
reset()
```

Those should remain separate application use cases if needed.

---

## Pipeline

`PipelineUseCases` was considered but is unnecessary abstraction for this project.

Final direction:

```python
@dataclass(slots=True)
class Pipeline:
    account_loader: AccountLoader
    account_risk_check: AccountRiskCheck
    market_scanner: MarketScanner
    data_collector: MarketDataCollector
    buzz_scanner: BuzzScanner
    news: NewsFeed
    ai: AiAnalyser
    technical_filter: TechnicalFilter
    composite_scorer: CompositeScorer
    watch_stocks: WatchStocks
    signals: Signals
    order_execution: OrderExecution
    reporting: Reporting
    technical_settings_repository: ITechnicalSettingsRepository
    logger: ILoggingProvider
```

Reasons:

- removes boilerplate `__init__`
- dependencies stay explicit
- no service locator
- no extra dependency-bundle class
- `slots=True` prevents accidental dynamic attributes

Keep the original workflow comments/docstrings when refactoring `Pipeline`.

---

## Workflow Strategy Selection

Normal workflows:

```python
settings = await self.technical_settings_repository.load()
strategy = settings.active_strategy
```

Buzz workflow:

```python
settings = await self.technical_settings_repository.load()
strategy = settings.buzz_strategy
```

Do not hard-code `"buzz"` inside the pipeline.

---

## Existing Technical Domain Files

Keep the current categorised criteria structure.

Do not merge all criteria into one file.

```text
a_domain/rules/technical/
├── strategy.py
├── calculation/
└── criteria/
    ├── momentum/
    ├── trend/
    ├── volatility/
    ├── volume/
    └── timing/
```

`criteria/` already has good SRP boundaries.

The main technical-domain change is `strategy.py`.

---

## Files to Remove After Migration

Remove the old configuration/factory architecture once no consumers reference it:

```text
backend/src/b_application/factories/technical_strategy.py
backend/src/b_application/schemas/technical_strategies.py
config/strategies.yaml
```

If `b_application/factories/` becomes empty, remove that directory too.

Remove old technical-strategy configuration from `AppConfig`, including old structures such as:

```text
ScoringConfig
StrategyThresholds
AppConfig.scoring
AppConfig.indicators
AppConfig.strategies
AnalysisConfig.active_strategy
```

Technical strategy settings now belong to `technical.yaml` / `TechnicalSettings`.

Keep general application settings such as:

```text
analysis.lookback_days
technical_weight
ai_weight
risk settings
execution provider
environment
database
AI provider
notifications
```

---

## Files Affected by the Migration

Core:

```text
backend/src/a_domain/model/analysis/technical_settings.py
backend/src/a_domain/ports/analysis/technical_settings_repository.py
backend/src/a_domain/rules/technical/strategy.py
backend/src/a_domain/types/enums.py

backend/src/c_infrastructure/technical/
    technical_settings_schema.py
    yaml_technical_settings_repository.py

backend/src/b_application/pipeline.py
backend/src/b_application/use_cases/collect/market_data_collector.py
backend/src/b_application/schemas/config.py

backend/src/c_infrastructure/system/config_loader.py

backend/src/d_presentation/cli/cli_container.py
backend/src/d_presentation/dependencies/repositories.py
backend/src/d_presentation/dependencies/use_cases.py

config/technical.yaml
config/appsetting.yaml
```

Tests should cover:

```text
YAML → typed criterion mapping
TechnicalRule effects
invalid configuration
hot reload between workflow runs
active strategy lookup
buzz strategy lookup
```

---

## Future Quant Direction

The current project is a rule-based / algorithmic trading prototype rather than a complete quantitative trading platform.

The existing architecture can grow toward quant trading without rewriting the technical domain.

Future additions may include:

```text
Historical Data
↓
Factors / Strategies
↓
Backtesting
↓
Performance Statistics
↓
Portfolio Construction
↓
Risk Management
↓
Paper Trading
↓
Live Execution
```

Keep criteria and future quantitative factors separate:

```text
Criterion
→ bool
→ screening / gating

Factor
→ numeric value
→ ranking / portfolio construction
```

Do not force numerical quant factors into the current `TechnicalCriterion` abstraction.

---

## Final Design Principles

```text
TechnicalSettings
= complete user technical configuration

TechnicalStrategy
= executable strategy

IndicatorParameters
= how indicators are calculated

TechnicalCriterion
= how one condition is evaluated

TechnicalRule
= how the strategy reacts to that criterion

RuleEffect
= explicit scoring/filter behaviour

Repository
= persistence abstraction

Pydantic
= external data validation

icontract
= domain invariants
```

The architecture should remain explicit, typed, local-first, hot-reloadable, and easy to extend without introducing factories, registries, dynamic imports, or unnecessary abstraction layers.
