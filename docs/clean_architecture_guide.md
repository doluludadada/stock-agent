# Clean Architecture Guide

How Hsiu structures a Python backend, written so that it works for any project. It comes from
three projects (accdatacontrol, stock-agent, Duoary) and from the review of stock-agent on
2026-11-01 (section 11).

This guide is the only rulebook. A project's `AGENTS.md` points here and adds facts about that
project, such as commands, paths and skills. It never changes a rule. Codex reads `AGENTS.md`,
and the project's `CLAUDE.md` holds only the line `@AGENTS.md` so that Claude Code reads it too.

---

## 0. What wins

Some rules below pull against each other. Decide in this order:

1. **Less code that a reader understands at a glance.** Fewer files, fewer classes, fewer layers.
   Do not rebuild what the standard library, pydantic or another dependency already does.
2. **The same concept in one place.** What a concept needs lives in that concept's file.
3. **The mechanical rules** in sections 2 to 7.

If following a rule would need a new file, class, wrapper or pass-through method, stop and report
the conflict instead of adding it.

The architecture check at 0 is not done. Done is the check at 0 **and** every judgment item of
the checklist at the end passing on the diff.

---

## 1. The idea in one picture

```text
d_presentation   → how the outside world starts something (API, CLI, scheduler)
c_infrastructure → how we talk to real things (database, files, email, AI, other APIs)
b_application    → the story of each operation, step by step
a_domain         → what the business is and what it decides
```

- The letter in front of each folder is the dependency order. A layer may import only the
  letters before it.
- `a_domain` imports nothing from the other three folders.
- `c_infrastructure` implements the interfaces (ports) that `a_domain` declares.
- One file in `d_presentation` (`dependencies.py`) builds every object and wires them
  together. No other place creates adapters.

---

## 2. Python 3.14

Write for Python 3.14. The project's `AGENTS.md` names the exact version.

- No `from __future__ import annotations`. Python 3.14 evaluates annotations lazily.
- A method that returns its own class returns `Self`.
- An alias is a `type` statement: `type Price = Annotated[float, Field(gt=0)]`.
- A generic uses the bracket syntax: `class Page[T]:` and `def first[T](items: Sequence[T]) -> T:`.
- Write `X | None`, `list[str]` and `dict[str, int]`. Abstract types come from `collections.abc`
  (`Sequence`, `Mapping`, `Iterator`, `AsyncGenerator`).
- An `@asynccontextmanager` function returns `AsyncGenerator[T]`. `AsyncIterator[T]` is deprecated there.
- Branch on an enum or a shape with `match`.
- Every overriding method has `@override` (`from typing import override`).
- Catch several exceptions without parentheses: `except OSError, ValueError:`.
- Every `datetime` carries a time zone.
- No comment that repeats the file's path.

---

## 3. Domain (`a_domain/`)

The domain answers two questions: **what things exist** (models) and **what the rules are**
(rules). It does not know about databases, HTTP, files or the clock.

### 3.1 One style for every domain class

Every model and every rule is a pydantic dataclass, and pydantic is the only validation.

```python
from dataclasses import replace
from typing import Annotated, Self

from pydantic import ConfigDict, Field, model_validator, validate_call
from pydantic.dataclasses import dataclass
```

- A **value** never changes: `@dataclass(frozen=True)`, plus `order=True` when values sort. To
  change one, call `replace(value, field=...)`, which validates again.
- An **entity** has an identity and a life, such as an order or an account:
  `@dataclass(config=ConfigDict(validate_assignment=True))`. Its methods change it in place, and
  pydantic validates every assignment.
- A limit on one field is a `Field(...)`. A limit that several classes share is one `type` alias
  in `a_domain/types/values.py`.
- A check across fields is one `@model_validator(mode="after")`.
- A method checks its arguments with `@validate_call` and the same types. A failed
  `model_validator` does not undo an assignment, so an entity's method checks first and changes
  after.
- Not used: `icontract`, checks in `__post_init__`, a hand-written `raise ValueError` for a limit
  that a `Field` can say, and `BaseModel` or `SQLModel` in the domain.

```python
type Quantity = Annotated[int, Field(gt=0)]


@dataclass(config=ConfigDict(validate_assignment=True))
class Account:
    account_id: Annotated[str, Field(min_length=1)]
    cash: Annotated[float, Field(ge=0)]
    positions: list[Position] = Field(default_factory=list)

    @validate_call
    def sell(self, stock_id: str, quantity: Quantity, cash_delta: float) -> int:
        position = self.position_for(stock_id)

        if position is None:
            raise PositionNotFoundError(stock_id)

        ...
```

### 3.2 Models (`a_domain/model/<area>/<concept>.py`)

- One file per concept. The file holds the concept's main class and its parts.
- `a_domain/model` holds only the business's standard models: the things a trader names, such as a
  stock, an order, an account and its positions, a signal, a watchlist entry, an EPS figure and a
  run's record, and their parts. Everything else has another home:
  - A rule's result, or a value only one rule reads, lives in that rule's file (3.5).
  - A small value that several areas share, such as a fiscal quarter, lives in `types/values.py` (3.3).
  - A type that only one port and its adapters use lives in the port's file (3.4).
  - Information that only a table or an API needs, such as a row's position or a display copy,
    lives in the DTO (5) or the response (6).
- Before adding a class, find the concept it belongs to and put it in that file. Before adding a
  file, check that no concept file fits.
- One idea is one class. Two classes with the same fields or the same derived value (such as
  `equity = cash + market_value`) are one class.
- A class with one field and no behavior of its own is that field. Use the field. A small class
  that describes only one model, such as a post's sentiment, is fields of that model.
- Never copy a model's fields into a second class to store it, send it or show it. Save and return
  the model, and give it the field it lacks. The architecture check's MODEL-COPY reports a class
  whose fields are mostly another model's.
- Name a class for what it is. `Report` names a document a person reads, such as a technical
  report. What a broker says about one exchange order is an `ExchangeOrder`.
- A model holds its data, the values derived from its own fields that need no setting and choose
  nothing (`Order.remaining_quantity`, `Eps.period_label`), and the changes of its own life
  (`Order.fill`).
- Code that takes a setting or a threshold, or chooses between outcomes, is a rule (3.5). A
  constructor that decides is a rule too: building three price scenarios from a configured spread
  is a rule.
- Use the domain model everywhere you can, including as the API answer. Do not copy its fields
  into a second class (a DTO or "view") without a concrete reason, such as "the client may only
  send part of it" or "this reader must not see part of it".
- What one screen shows, built from several models, is not a domain model. It belongs in
  `PipelineStatus` and the presentation layer (4.3).

### 3.3 Types and constants (`a_domain/types/`)

- `enums.py`: every enum, each a `StrEnum`, so it saves as readable text.
- `errors.py`: the domain's own exceptions.
- `ids.py`: the id types.
- `values.py`: the `type` aliases for limits that several classes share, and the small value
  classes that several areas share, such as `FiscalQuarter`.

Every constant has one of two homes:

- A fixed name, kind, status or label is a member of a `StrEnum` in `enums.py`. The text a user
  sees for it is the enum's `label` property.
- Everything else is a setting (4.4): numbers, limits, dates, deadlines, time windows,
  sentences, templates, URLs and model names.

Models, rules and use cases have no module-level constants.

A life cycle lives on its status enum. Each member documents what it means, and the enum says
which statuses may follow each one. The model asks its status and keeps no table of its own.

```python
class OrderStatus(StrEnum):
    PENDING = "pending"
    """Built by the app, not yet accepted by a broker."""

    SUBMITTED = "submitted"
    """Accepted and working. It may hold a partial fill."""

    FILLED = "filled"
    """The whole quantity executed."""

    CANCELLED = "cancelled"
    """Stopped before the whole quantity executed. It may hold a partial fill."""

    @property
    def next_statuses(self) -> frozenset[OrderStatus]:
        """SUBMITTED to SUBMITTED is a partial fill that leaves the rest working."""
        match self:
            case OrderStatus.PENDING:
                return frozenset({OrderStatus.SUBMITTED, OrderStatus.CANCELLED})
            case OrderStatus.SUBMITTED:
                return frozenset({OrderStatus.SUBMITTED, OrderStatus.FILLED, OrderStatus.CANCELLED})
            case _:
                return frozenset()

    @property
    def is_open(self) -> bool:
        return bool(self.next_statuses)
```

`Order` checks `status in self.status.next_statuses` before it moves, and raises
`IllegalOrderTransition` from `errors.py` when the move is not listed.

### 3.4 Ports (`a_domain/ports/<area>/`)

A port is a promise: "someone will give me this". The domain says what it needs; the
infrastructure decides how.

- Each port is a `typing.Protocol` whose name starts with `I` (`IOrderRepository`,
  `ILoggingProvider`, `INotificationProvider`).
- Group ports by concern in sub folders, and re-export them from each `__init__.py`.
- Methods take and return domain models, never database rows or DTOs.
- I/O methods are `async`.
- If an adapter needs a helper, the helper is a method on the port, not a private method in the
  adapter. Section 5 names the one kind of infrastructure code that is never a port method.
- A type that only this port and its adapters use lives in the port's file.

```python
class IOrderRepository(Protocol):
    async def get(self, order_id: OrderId) -> Order | None: ...

    async def save(self, order: Order) -> None: ...
```

### 3.5 Rules (`a_domain/rules/<area>/<concept>.py`)

A rule is one business decision you can test on its own.

- One file per concept, like models. The file holds the rule and the classes only that rule
  uses: the parts of its settings, its inputs and its result. A cost rule's file holds the rule
  and the cost it returns.
- A rule class has exactly one public method, `apply`, and only `apply` decides. Like a model
  (3.2), a rule may also expose read-only properties derived from its own fields that choose
  nothing, such as `TechnicalStrategy.required_bars`, the daily bars its formulas need. A class in
  a rule file with only fields and properties is one of the rule's values, not a rule.
- Use cases call rules, and rules may call other rules. The Pipeline and the presentation layer
  never call a rule.
- Keep a rule easy: a few checks a reader understands at a glance. If it grows, split it into
  two rules.
- A rule that needs settings receives them as plain fields (`int`, `bool`, `frozenset`). It
  never receives the whole config object.
- The rule never reads the clock. The caller passes `now`.
- Write each check as a short block that ends in an early `return`. No nested `if`.
- A decision used in more than one place, or with more than two branches, belongs in a rule,
  not in a use case.

```python
@dataclass(frozen=True)
class FreeShippingRule:
    minimum_total: Annotated[int, Field(ge=0)]
    excluded_regions: frozenset[str]

    def apply(self, order: Order, region: str) -> bool:
        if region in self.excluded_regions:
            return False

        return order.total >= self.minimum_total
```

---

## 4. Application (`b_application/`)

The application layer tells the story of each operation. Reading a Pipeline method should feel
like reading a list of steps in plain English.

### 4.1 Use cases (`b_application/use_cases/<area>/`)

- A use case is one step that a person would name: load the account, scan the market, send the
  orders. It calls every port and rule that the step needs.
- A rule call is never a use case by itself. It goes inside the use case whose step needs its
  answer.
- One use case class per file, grouped by area in sub folders.
- Each use case has exactly one public method, always named `execute`.
- `__init__` receives ports and settings, and builds its rules from the settings.
- `execute` returns its result. It may read `PipelineStatus` for its inputs and add to
  `status.stats` (counters and errors). It writes no other field of the status.
- Use cases only orchestrate. No SQL, no data mapping, no business calculations inside them.
- No private methods. A helper becomes a domain rule, a port method or a model method.
- Use cases do not call each other. The Pipeline puts them in order.

### 4.2 Pipeline (`b_application/pipeline.py`)

The Pipeline holds every operation the outside world can start.

- There is exactly one class, `Pipeline`. Its fields are the use cases and the logger. It has no
  ports, no rules, no settings and no classes that group its fields.
- The presentation layer calls only `Pipeline` methods. Each public method is one operation,
  including an operation with one step.
- An operation is a flat list of use case calls, in order. The Pipeline stores each result in
  `PipelineStatus`, so the Pipeline shows where every field of the status comes from:

```python
async def checkout(self, cart_id: CartId) -> PipelineStatus:
    status = PipelineStatus()
    status.cart = await self.load_cart.execute(cart_id)
    status.discounts = self.apply_discounts.execute(status)
    status.order = await self.place_order.execute(status)
    await self.send_receipt.execute(status)
    return status
```

- The Pipeline makes no business decision. Its only `if` stops an operation when a step left
  nothing to work on. It may name a rule's value type in an annotation, such as
  `settings: TechnicalSettings`, but it never calls a rule.
- A long batch run (a nightly job) is also an operation. Wrap it so the run is always marked as
  running, then success or failure, and the `finally` block always does the clean-up and the
  notification. On failure, record it and re-raise.

### 4.3 Pipeline status (`b_application/schemas/pipeline_status.py`)

- There is exactly one `PipelineStatus` class, a mutable `dataclasses.dataclass` that carries
  everything between steps. It validates nothing, so it uses the standard library dataclass.
- Only the Pipeline writes its fields. Use cases add to `status.stats`.
- It may offer small checks such as `status.require_order()`, which raises if an earlier step did
  not load the order.
- What a screen shows is a set of fields on `PipelineStatus`, turned into a response class in
  `d_presentation` (`OrderSummaryResponse.from_status(status)`), not a new domain model.
- `b_application/schemas` holds only `PipelineStatus`. What an operation hands a screen is fields of
  the status, never a report class.

### 4.4 Settings (`b_application/config/`)

- A pydantic settings class loaded from a YAML file, with secrets from `.env`.
- Every constant that is not an enum member lives there (3.3), and so does every value a
  business person might want to change.

---

## 5. Infrastructure (`c_infrastructure/`)

- Every class here implements a port. It has only that port's methods, and each one is marked
  `@override`.
- One folder also holds code that implements no port: `c_infrastructure/database/models/`. Next to
  the tables (DTOs) it holds code whose subject is the tables themselves and never a domain model:
  the schema upgrade steps, which run on a raw connection; the owner guard that the database
  connector installs on every session it opens; the key derivation and sealing of the users
  table's columns; and the copies of the whole database that backups and restores make. Such code has no domain meaning, so it is never a port method. A port that named
  a session hook, a storage name or a cipher would put a library's detail into the domain. Module
  functions and plain classes are allowed in that folder for this code only. Any other helper of an
  adapter is a port method (3.4), and a name the wiring can compute, such as a collection name, is
  passed to the adapter's constructor.
- Infrastructure carries data in and out. It makes no domain decision.
- Database rows (DTOs) live only here, one DTO file per area, and are converted to domain models
  here. `SQLModel` is used only for these tables. Information only a table needs, such as a row's
  position in a list or a JSON column, belongs to the DTO and never to a model.
- The database carries the schema version of the code that created or last upgraded it. A
  change to an existing table, or to how a column stores its value, appends an upgrade step, which
  raises the code's schema version. A step names the tables and columns as they were at its
  version, never through today's table classes. A new table needs no step, because startup
  creates it. Startup never upgrades a database. It refuses an older one, and the migrate command
  upgrades it after a backup. A test compares the table classes with a committed snapshot of the
  current version's tables, so a change to an existing table without a step fails the tests.
- A query lives in the repository for the table it is about.
- Logging goes through the logging port (for example a loguru adapter). Log ids and counts, never
  private user content.

---

## 6. Presentation (`d_presentation/`)

- Routers and CLI commands only: read the input, call one `Pipeline` method, return the answer.
  No business decisions, and no copy of a domain rule.
- The database commands (`just db-*`) are the one exception. They must open a database that
  startup refuses, so no Pipeline exists yet, and they call the database connector's port
  directly. No other command or route calls a port.
- Presentation code may name a domain type in a request, a response or a signature, even a type
  from a rule file, but it never runs a rule.
- `dependencies.py` is the only place that creates objects. Plain functions are enough; cache
  shared adapters with `@lru_cache()`.
- Request and response classes exist only for the reasons in 3.2.

---

## 7. Code style

- Every function at most 30 lines, cyclomatic complexity at most 10. Two kinds of function are
  exempt from the length limit, but not from the complexity limit:
  - The builders in `dependencies.py`. One constructor argument per line is wiring, not logic,
    and splitting it would add groups.
  - The operations in the Pipeline (4.2). An operation is a flat list of use case calls.
    stock-agent's operations send orders with the same inline five-line loop five times: twice in
    Buzz, twice in Intraday and once in the manual BUY. Splitting an operation would hide the
    order of its steps.
- Reduce nesting only with early returns.
- Names say what something is. No single-letter names except `i`, `j`, `k` in loops. No
  abbreviations (`membership`, not `mship`; `configuration` or `config`, but pick one).
- No vague names such as manager, handler, processor, helper, util or service, unless the name
  states a precise job.
- One word per thing across code, comments, settings and docs. If something is called
  `candidate` in one file, it is `candidate` everywhere. Never add a second name for an existing
  concept.
- Code, comments and docs are in English.
- Comments say what the code does in words. No ticket numbers or story ids (`US-304`).
- No hard-coded values. Section 3.3 gives every constant its home, and rules and use cases
  receive settings through their constructor.

---

## 8. When to add something new

Do not add a service, factory, mapper, wrapper, adapter, DTO, helper or class unless it:

- removes real duplication,
- isolates a real dependency, or
- represents a real business concept.

"It might be useful later" is not a reason. Before adding a field, enum, class or method, search
for an existing one with the same meaning. Keep one source of truth for each piece of state, do
not hold the same state in two fields, and do not repeat validation, mapping, filtering or
conversion logic. Delete the old implementation when you replace it, and keep no compatibility
code unless the task asks for it.

---

## 9. Checks

- The type checker (`pyright`) ends with 0 errors, with `reportImplicitOverride` turned on. No
  `# type: ignore`.
- `tools/architecture_check.py` checks the rules a script can see. It cannot see a class in the
  wrong concept file, one idea held by two classes, or a use case that only wraps a rule. The
  judgment items of the checklist cover those.
- Domain rules are unit-tested directly. Use cases and operations are tested through their
  public methods with fake ports.
- Tests check what a caller can observe, not internal details.

---

## 10. Working with an agent

- When a request is unclear, ask before writing code.
- Change only the files the task needs. List every file to add, change and delete.
- If the task needs more changes than were asked for, say so before making them.
- Leave no deprecated code, unused import, compatibility branch or duplicate implementation.
- Before returning code, go through the whole checklist below, judgment items included, and check
  that every caller, implementation, wiring, test, API schema and frontend consumer still matches.

---

## 11. Mistakes this guide was changed to stop

Each one below followed a mechanical rule and broke section 0. They come from stock-agent.

- A "one class per file" rule split one watchlist concept into `watchlist_entry.py`,
  `stock_watchlist.py` and `watchlist_addition.py`, and left loose constants in whichever file was
  nearest. One concept is one file.
- A "rule files hold only `apply`" check moved `TradeCost`, `TechnicalRule` and
  `TechnicalScoring` out of the rule files that use them and into `model/`. A rule's own values
  stay in its file.
- Five classes computed `equity = cash + market_value` or `market_value`: `AccountValuation`,
  `AccountSnapshot`, `EquityPoint`, `PositionValuation` and `PositionSnapshot`. One idea is one
  class.
- `StockWatchlist` wrapped a single `list[Stock]`. A class with one field and no behavior is that
  field.
- `AccountEquity`, `AnalysisCandidates` and `DecisionCandidates` were use cases that each wrapped
  one rule call. A rule call goes inside the step that needs it.
- Five classes (`CollectSteps`, `ProcessSteps`, `TradingSteps`, `ChatSteps`, `ValuationSteps`)
  grouped the Pipeline's fields, and some fields appeared in two groups. The Pipeline's fields
  are its use cases.
- The domain validated with three tools (`icontract`, pydantic, hand-written `raise`) in three
  model styles. Section 3.1 picks one.
- 18 files imported `from __future__ import annotations` on Python 3.14, which does not need it.
- A display name sat in a module dict (`SOURCE_LABELS`) next to enums that already had a `label`.
  Display names are enum labels.
- A 7-day grace period (`FILING_GRACE`) and the filing deadlines were written in a model file.
  Time windows and deadlines are settings.

From the owner's review of the model folder on 2026-11-04:

- `StockReport` copied seven fields of `Stock` so the journal could store a run's analysed
  stocks, and `AccountValue` and `PositionValue` copied `Account` and `Position` to carry a price.
  Save the model, and give it the field it lacks.
- `BrokerOrderReport` and `WatchlistAddition` sat in model files although each was what one rule
  reads or returns. A rule's values live with the rule.
- `SentimentClassification` was a two-field class that only described a post. It is fields of
  the post.
- `FiscalQuarter` carried the filing-deadline and trailing-twelve-months knowledge of two rules in
  the EPS model file. The rules hold that knowledge; the quarter is a shared value.

From the review of the user accounts on 2026-11-04:

- The owner guard and the users table's key derivation sat under `c_infrastructure/database/models/`
  because the architecture check skips that folder, and no rule said what belongs there. Section 5
  now says what may live there, and why it is never a port method.
- `IKnowledgeRepository.collection_name()` put a Chroma collection name and the legacy owner's
  special case into a domain port, only to obey "an adapter's helper is a method on the port". The
  wiring computes the name and passes it to the adapter.

---

## Checklist

Copy this list for a review.

**Judgment.** No script checks these.

- [ ] Every new class sits in the file of its concept. No new file where a concept file fits.
- [ ] No two classes hold the same idea, and no class wraps a single field.
- [ ] `a_domain/model` holds only standard models and their parts: no copy of a model, no rule
      result, no port-only type and no table-only information.
- [ ] Every use case is a step a person would name. None only wraps one rule call.
- [ ] The Pipeline only calls use cases and stores their results.
- [ ] The diff is the smallest one that does the job, and it rebuilds nothing a library does.

**Structure.**

- [ ] `a_domain` imports nothing from `b_`, `c_` or `d_`, and no database, web or HTTP library.
- [ ] Every domain class is a pydantic dataclass. Validation uses only `Field`, `type` aliases,
      `model_validator` and `validate_call`.
- [ ] Constants are `StrEnum` members in `enums.py` or settings. No module-level constants.
- [ ] Every port is a `Protocol` starting with `I`, and uses domain models only.
- [ ] Every rule makes one easy decision in one `apply` method, gets plain settings, and is
      passed the time.
- [ ] Every use case has one `execute` method that returns its result, writes only
      `status.stats`, has no private methods, and calls no other use case.
- [ ] One `Pipeline` whose fields are only use cases and the logger. One `PipelineStatus`.
- [ ] Infrastructure classes implement a port and mark every method `@override`.
- [ ] Only `dependencies.py` creates objects.
- [ ] Python 3.14 style from section 2.
- [ ] Functions ≤ 30 lines, complexity ≤ 10, early returns, no single-letter or shortened names.
- [ ] Same word for the same thing everywhere. No story numbers in comments.
- [ ] `pyright` at 0 errors, the architecture check at 0 and the tests pass.
