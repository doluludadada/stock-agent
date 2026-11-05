## Implemented — 2026-11-03

The custom-formula design is implemented and described in [Technical strategy formulas](technical-strategy-formulas.md).
The sections below are the history that led to it.

## Latest implementation handoff — 2026-11-03

Read the [中文交接文件](strategy-implementation-handoff-2026-11-03.zh-TW.md) for the latest
custom-formula direction, SQL normalization preference, all review items and the verified
current checkout status. It supersedes conflicting storage and formula proposals below.
The refactor is incomplete; historical verification claims do not apply to this checkout.

## Earlier designer direction — 2026-11-03

Read [Strategy designer](strategy-designer.md) for the agreed flexible editor, built-in quick
fills, custom strategies and volume comparisons, plus the proposed all-JSON format, hybrid
SQL tables, concrete condition engine and project data flow. Its implementation outline is
proposed, not a claim that the current checkout implements it. Earlier conflicting UI and
YAML-text-in-SQL proposals below are historical context.

## Confirmed strategy scope — 2026-11-02

- The developer maintains three YAML presets:
  Conservative, Balanced, and Aggressive.

- The CLI only loads those three presets.
  It does not provide strategy editing, import/export,
  or custom-strategy management screens.

- Editing and saving are backend API responsibilities.
  Future website and iOS frontends use the same API.

- New users receive independent default settings automatically.
  Existing saved settings are preserved on subsequent use.

- YAML remains the preset and persisted strategy-document format.

- Local execution uses SQLite.
  The deployed service uses a separate PostgreSQL database.
  Database selection is explicit.

- Website and iOS share the service database through the API.
  Saved settings are scoped by authenticated account.

- Chroma continues its memory/knowledge role.
  Private Chroma-backed data must also be account-scoped.

- Named rule definitions move into YAML.
  Indicator calculations and generic evaluation remain in Python.

- Tests must cover the three CLI preset choices,
  preset immutability, automatic defaults, API validation,
  account isolation, and settings shared across clients.

## Strategy redesign decision — 2026-11-02

### Baseline

The original repository is the implementation baseline.
Previous ZIP changes have not been applied.

### Objective

Move named rule definitions and strategy composition into YAML.

Users can define names, indicator parameters, operands, operators,
condition groups, and rule effects without adding a Python criterion
class for each combination.

### Code responsibilities

Python retains:

- Indicator calculations.
- Supported comparison and crossing operations.
- Condition grouping.
- Validation.
- Strategy evaluation and scoring.

Rule names and preset names never select Python implementations.

### Intended technical structure

Keep and adapt:

- rules/technical/strategy.py
- rules/technical/calculation/calculator.py
- rules/technical/calculation/formulas.py

Replace criteria/base.py with a generic condition.py.

Delete the old rules/technical/criteria/ package after presets,
schemas, callers, saved documents, and tests use the replacement.

Do not delete the entire rules/technical/ directory.

### Persistence recommendation

- Shipped presets and initial defaults: config/technical.yaml.
- Local saved settings: SQLite.
- Service saved settings: separate PostgreSQL.
- Saved document format: YAML text.
- Editing/import/export: YAML.
- Select the database backend explicitly.
- No automatic local/service synchronization.

Initially store one settings document per owner:
owner_id, settings_yaml, revision.

### User defaults

Initialize independent settings automatically on first use.
Read the initial selection from configuration.
Preserve active_strategy_id as the default-selection concept.
Do not overwrite saved settings on subsequent launches.
Migrate existing local YAML settings before seeding fresh defaults.
Preset updates do not mutate existing user copies.

### Interface

Use the CLI now.
Defer frontend development.

Provide list, copy, export, import/save, select-default,
and explicit restore operations.

### Verification

Test external rule definitions, label-independent evaluation,
comparisons/crossings, grouping/scoring, initialization,
preset-copy independence, persistence, and owner/database isolation.

Existing cleanup tests do not establish that the redesigned engine
has been implemented.
