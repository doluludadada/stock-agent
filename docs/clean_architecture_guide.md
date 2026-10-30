# Clean Architecture Guide

How Hsiu structures a Python backend, written so that it works for any project. It comes from
three projects (accdatacontrol, stock-agent, Duoary) and keeps only what they agree on, plus
the rules Hsiu settled during Duoary.

Give this file to an agent with the words "build or check the code against this guide".
Where a project has its own rules file, that file wins.

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

## 2. Domain (`a_domain/`)

The domain answers two questions: **what things exist** and **what the rules are**.
It does not know about databases, HTTP, files or the clock.

### 2.1 Models (`a_domain/model/<area>/`)

- One class per file. One sub folder per area of the business (`order/`, `account/`, ...).
- A model is a dataclass. `SQLModel` (and so Pydantic) is also allowed.
- Use the domain model everywhere you can, including as the API answer. Do not copy its fields
  into a second class (a DTO or "view") without a concrete reason, such as "the client may only
  send part of it" or "this reader must not see part of it".
- Before adding a small new class, check whether it is really part of an existing model. Fold
  it in if it is.
- What one screen shows, built from several models, is not a domain model. It belongs in the
  application or presentation layer (see 3.3).
- Pick one style per project and keep it:
  - **Frozen models** (`@dataclass(frozen=True, kw_only=True)`) whose methods return a new
    instance. Good when objects are edited one at a time.
  - **Plain mutable models** that rules fill in place. Good for batch jobs that process many
    rows in one run.

```python
@dataclass(frozen=True, kw_only=True)
class Order:
    customer_id: UUID
    total: int
    id: UUID = field(default_factory=uuid4)
    version: int = 1

    def change_total(self, total: int, expected_version: int) -> "Order":
        if expected_version != self.version:
            raise OrderVersionConflictError(self.id, self.version)

        return replace(self, total=total, version=self.version + 1)
```

### 2.2 Types (`a_domain/types/`)

- `enums.py`: every enum is a `StrEnum`, so it saves as readable text.
- `errors.py`: the domain's own exceptions.

### 2.3 Ports (`a_domain/ports/<area>/`)

A port is a promise: "someone will give me this". The domain says what it needs; the
infrastructure decides how.

- Each port is a `typing.Protocol` whose name starts with `I` (`IOrderRepository`,
  `ILoggingProvider`, `INotificationProvider`).
- Group ports by concern in sub folders, and re-export them from each `__init__.py`.
- Methods take and return domain models, never database rows or DTOs.
- I/O methods are `async`.
- If an adapter needs a helper, the helper is a method on the port, not a private method in the
  adapter.

```python
class IOrderRepository(Protocol):
    async def get(self, order_id: UUID) -> Order | None: ...

    async def save(self, order: Order) -> None: ...
```

### 2.4 Rules (`a_domain/rules/<area>/`)

A rule is one business decision you can test on its own.

- One class per decision, with exactly one public method, always named `apply`.
- Keep a rule easy: a few checks a reader understands at a glance. If it grows, split it into
  two rules.
- A rule that needs settings is a frozen dataclass and receives them as plain fields
  (`int`, `bool`, `frozenset`). It never receives the whole config object.
- The rule never reads the clock. The caller passes `now`.
- Write each check as a short block that ends in an early `return`. No nested `if`.
- A decision used in more than one place, or with more than two branches, belongs in a rule,
  not in a use case.

```python
@dataclass(frozen=True)
class FreeShippingRule:
    minimum_total: int
    excluded_regions: frozenset[str]

    def apply(self, order: Order, region: str) -> bool:
        if region in self.excluded_regions:
            return False

        return order.total >= self.minimum_total
```

---

## 3. Application (`b_application/`)

The application layer tells the story of each operation. Reading a use case should feel like
reading a list of steps in plain English.

### 3.1 Use cases (`b_application/use_cases/<area>/`)

- One use case class per operation, one class per file (`PlaceOrderUseCase`,
  `CancelOrderUseCase`). Group the files by area in sub folders.
- Each use case has exactly one public method, always named `execute`.
- `__init__` receives ports and settings, and builds its rules from the settings.
- `execute` is one whole operation: it logs what it does, loads, calls rules or model methods,
  saves, and returns.
- Use cases only orchestrate. No SQL, no data mapping, no business calculations inside them.
- No private methods. A helper becomes a domain rule, a port method, or a public step.
- Use cases do not call each other. When an operation needs several use cases, it is a workflow
  (3.2).
- No method that only passes a call through. If a step only reads or saves, call the port.

### 3.2 Pipeline (`b_application/pipeline.py`)

The pipeline holds the workflows: operations that need several steps or several use cases.

- There is exactly one `Pipeline` class.
- Each workflow is a flat list of steps, in order, that reads like a story:

```python
async def place_order(self, status: PipelineStatus) -> PipelineStatus:
    await self._load_cart.execute(status)
    await self._apply_discounts.execute(status)
    await self._place_order.execute(status)
    await self._send_receipt.execute(status)
    return status
```

- A step reads what it needs from `PipelineStatus` and writes its result back into it.
- A one-step operation does not go through the pipeline; the endpoint calls the use case
  directly.
- A long batch run (a nightly job) is also a workflow. Wrap it so the run is always marked as
  running, then success or failure, and the `finally` block always does the clean-up and the
  notification. On failure, record it and re-raise.

### 3.3 Pipeline status (`b_application/schemas/pipeline_status.py`)

- There is exactly one `PipelineStatus` class, a mutable dataclass that carries everything
  between steps.
- It may offer small checks such as `status.require_order()`, which raises if an earlier step did
  not load the order.
- What a screen shows is a set of fields on `PipelineStatus`, turned into a response class in
  `d_presentation` (`OrderSummaryResponse.from_status(status)`), not a new domain model.

### 3.4 Settings (`b_application/config/`)

- A Pydantic settings class loaded from a YAML file, with secrets from `.env`.
- Every value a business person might want to change lives there, not in the code.

---

## 4. Infrastructure (`c_infrastructure/`)

- Every class here implements a port. It has only that port's methods, and each one is marked
  `@override`.
- Database rows (DTOs) live only here, one DTO file per area, and are converted to domain models
  here.
- A query lives in the repository for the table it is about.
- Logging goes through the logging port (for example a loguru adapter). Log ids and counts, never
  private user content.

---

## 5. Presentation (`d_presentation/`)

- Routers and CLI commands only: read the input, call one use case operation or one pipeline
  workflow, return the answer. No business decisions.
- `dependencies.py` is the only place that creates objects. Plain functions are enough; cache
  shared adapters with `@lru_cache()`.
- Request and response classes exist only for the reasons in 2.1.

---

## 6. Code style

- Every function at most 30 lines, cyclomatic complexity at most 10.
- Reduce nesting only with early returns.
- Names say what something is. No single-letter names except `i`, `j`, `k` in loops. No
  abbreviations (`membership`, not `mship`; `configuration` or `config`, but pick one).
- One word per thing across code, comments, settings and docs. If something is called
  `candidate` in one file, it is `candidate` everywhere.
- Code, comments and docs are in English.
- Comments say what the code does in words. No ticket numbers or story ids (`US-304`).
- Follow SOLID and clean code without over-engineering.
- No hard-coded values. Numbers, limits, time windows, file paths, URLs, hosts, model names,
  email addresses and feature switches come from the settings file (`.env` for secrets).
  Fixed names such as statuses or kinds are a `StrEnum`, never a bare string repeated in the
  code. Rules and use cases receive these values through their constructor.

## 7. When to add something new

Do not add a service, factory, mapper, wrapper, adapter, DTO or helper unless it:

- removes real duplication,
- isolates a real dependency, or
- represents a real business concept.

"It might be useful later" is not a reason. Before adding a field, enum, class or method, search
for an existing one with the same meaning. Keep one source of truth for each piece of state, and
delete the old implementation when you replace it.

## 8. Checks

- Type checker (`pyright`) runs in the lint command and ends with 0 errors, with
  `reportImplicitOverride` turned on. No `# type: ignore`.
- Domain rules are unit-tested directly. Use cases and workflows are tested through their
  public methods with fake ports.
- Tests check what a caller can observe, not internal details.

## 9. Working with an agent

- When a request is unclear, ask before writing code.
- Change only the files the task needs. List every file to add, change and delete.
- If the task needs more changes than were asked for, say so before making them.
- Before returning code, check: no new helper without a reason, no duplicated state, no private
  method, dependency direction kept, every implementation has `@override`, and every caller and
  test still matches.

---

## Review checklist

Copy this list for a quick check.

- [ ] `a_domain` imports nothing from `b_`, `c_` or `d_`, and no database, web or HTTP library.
- [ ] One class per model file. No class that only copies another model's fields.
- [ ] Every port is a `Protocol` starting with `I`, and uses domain models only.
- [ ] Every rule makes one easy decision in one `apply` method, gets plain settings, and is
      passed the time.
- [ ] Every use case is one operation with one `execute` method, only orchestrates, has no
      private methods, and does not call another use case.
- [ ] One `Pipeline`, one `PipelineStatus`. Multi-step operations are flat workflows.
- [ ] Infrastructure classes implement a port and mark every method `@override`.
- [ ] Only `dependencies.py` creates objects.
- [ ] Functions ≤ 30 lines, complexity ≤ 10, early returns, no single-letter or shortened names.
- [ ] No hard-coded values: settings come from the settings file, fixed names from a `StrEnum`.
- [ ] Same word for the same thing everywhere. No story numbers in comments.
- [ ] `pyright` at 0 errors and tests pass.
