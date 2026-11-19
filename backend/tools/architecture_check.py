"""Check backend source code against docs/clean_architecture_guide.md.

Run from backend/:

    uv run python tools/architecture_check.py [--pyright] [paths ...]

Paths default to `src`. The checker prints one line per violation as `RULE-ID path:line message`,
then the number of violations per rule. It exits 1 when any violation exists, 0 when there is none,
and 2 on bad usage. It reads files with `ast` and `tokenize` and imports no project code.

A file's layer is the first folder in its path named a_domain, b_application, c_infrastructure or
d_presentation. Rules that name a folder apply below that folder; the others apply to every file.

How the rules measure:
- FUNC-LENGTH counts physical lines from the `def` line (decorators excluded) to the last line of the
  body, minus the lines of the docstring. Blank lines and comments inside the body count. A nested
  function is measured on its own and also counts toward the function that holds it. It skips
  dependencies.py, whose builders are flat lists of constructor arguments. It skips the Pipeline too,
  whose operations are flat lists of use case calls. The same inline five-line loop sends orders five
  times there, twice in Buzz, twice in Intraday and once in the manual BUY, and splitting an operation
  would hide the order of its steps. It skips a method named `execute` of a class in a file under
  b_application/use_cases as well: a use case is one function with one responsibility and has no private method
  to move lines into. Any other function of such a file is measured. Cyclomatic complexity is ruff's C901, which
  checks all three.
- RULE-APPLY never counts a method decorated `@property`, so a rule may expose read-only values derived
  from its fields, nor one decorated `model_validator` or `field_validator`, which pydantic calls and no caller
  does. A property's setter still counts. A method is public when its name does not start with `_`. A class with
  no public method is a value of the rule in its file. Every other class has `apply` and no other public method,
  static methods and class methods included. Dataclass fields are not methods.
- USECASE-EXECUTE allows only `__init__` and `execute`, and one class per use case file.
- INFRA-OVERRIDE lets `__init__` go unmarked and requires `@override` on every other public or dunder method. A
  `_name` or `__name` method is PRIVATE-METHOD's finding and is not reported here. It skips DTOs (`table=True`, or
  any class under c_infrastructure/database/models/), enums, exceptions and value holders (`BaseModel`, `SQLModel`,
  `BaseSettings`, `TypedDict`, `NamedTuple`, `@dataclass`, and their subclasses). A module-level function is an
  adapter's helper and is not reported.
- PRIVATE-METHOD reports every method whose name starts with `_` and is not a dunder (`__name__`), in every class
  of every file, a nested class and a class under c_infrastructure/database/models/ included. It skips no folder.
  A pydantic validator is a method too, so it is named without the underscore. A private attribute and a
  module-level function are not methods.
- PORT-CALLERS takes every method of a Protocol in a_domain/ports, dunder methods aside, and looks for an attribute
  read of its name in the files checked. The port's own file does not count, and neither does a file that defines a
  class descending from the port, a sub-port or an adapter: a method read nowhere else is a helper only its own
  adapter calls. It matches by name, so a method that shares its name with something another file reads counts as
  called. PORT_CALLERS_EXEMPT names the methods left on a port without such a caller, each with its reason.
- PORT-PROTOCOL treats every top-level class in a_domain/ports as a port, except a pydantic dataclass: that is a
  type only its port and the port's adapters use, and it lives in the port's file.
- FACTORY-ONLY treats a called name that starts with an upper-case letter as a class.
- PRESENTATION-DECIDES-NOTHING checks d_presentation except dependencies.py. An import of a_domain.rules is a
  finding unless it is annotation-only: a `from` import whose every name the file uses, and uses only inside the
  annotation of a parameter, a return or an annotated assignment. A call, an attribute read or a name passed as a
  value is a finding. A setting read is an attribute chain on a name or attribute called `config`, such as
  `runtime.config.line.channel_secret`. The chain must equal or extend an entry of the first PRESENTATION_SETTINGS
  key the file is under, a file key before its folder's; a file under no listed key may read none. Every class in
  d_presentation/web/schemas.py must define no method.
- STRATEGY-FROM-SETTINGS treats a call whose called name is TechnicalStrategy or TechnicalRule as building one, in
  any file. Strategies come from config/strategies/<id>.json and from the owner's saved settings, and pydantic
  validates them, so no source file calls either constructor.
- STORY-ID looks for `US-<number>`, any to-do marker and `#<number>` in comments and docstrings.
- HARDCODED-URL ignores docstrings.
- PATH-COMMENT reports a comment that holds the file's path from its layer folder down.
- DOMAIN-STYLE forbids icontract and the standard `dataclass` anywhere in a_domain. Below a_domain/model and
  a_domain/rules, every top-level class except enums, exceptions and Protocols is decorated with
  `pydantic.dataclasses.dataclass`, subclasses no BaseModel, RootModel or SQLModel, and has no `__post_init__`.
- MODULE-CONSTANT checks a_domain, b_application/use_cases, b_application/schemas and the Pipeline. Every top-level
  assignment other than `__all__`, `NewType` and `TypeVar` is a finding, an old-style alias included.
- PIPELINE-FIELDS allows only the class `Pipeline` in b_application/pipeline.py. Each annotated field's type must be
  imported from b_application.use_cases, or be the logging port.
- RULE-CALLERS checks a_domain, b_application and dependencies.py: only a_domain/rules, a_domain/ports (a port may
  name a rule's input or result type), b_application/use_cases and b_application/config (a settings class builds
  each rule from its own values, so a rule is configured in one place) there may import a_domain.rules. The Pipeline
  may also import it annotation-only, as PRESENTATION-DECIDES-NOTHING defines it. The rest of d_presentation is left
  to PRESENTATION-DECIDES-NOTHING. In c_infrastructure it reads the rule file an import names, from the disk, and
  sorts each imported name. A value is a class without an `apply` method, a type alias or an assignment, and an
  adapter may import it, since a port may name a rule's input or result type. A decision is a class with `apply` or
  a function, and so is a name the rule file does not define at its top level, a module included. Importing a
  decision is a finding unless INFRASTRUCTURE_RULES names it for that file, with the reason the port's promise is
  that rule's result. An entry of the table that its file no longer imports is a finding too.
- USECASE-STATUS treats `status`, and every parameter annotated `PipelineStatus`, as the run's status. Below
  b_application/use_cases it reports an assignment or deletion under any field but `stats`, a mutating collection
  method called on such a field, and a status method whose name does not start with `require_`.
- MODEL-COPY compares every class in a_domain/model and b_application/schemas that has at least two annotated fields
  with every class in a_domain/model. When at least 80% of its field names are fields or properties of another
  model, it copies that model, for storage, transport or a screen. Store, send and show the model itself; a DTO in
  c_infrastructure or a response in d_presentation holds only what the model lacks or must hide. Classes in
  a_domain/rules are not compared: sibling variants of one rule value share fields on purpose. In
  d_presentation/web/schemas.py it reports only exact copies: a class whose field names are exactly those of a class
  in a_domain/model, a_domain/types or a_domain/ports, with no field typed by a name the module defines (another
  response, which hides part of a model, or PublicText, which redacts). A route answers with that domain class itself.
- MODEL-HOME takes every top-level class in a_domain/model whose name nothing else in its own file uses, so it is no
  part of that file's concept, and the files of a_domain, b_application and d_presentation that import it by name. An
  adapter in c_infrastructure imports a rule's values and a port's types too, so it does not count. When those files
  are one rule file and any port files, which hand that rule's value over, the class is a value only that rule reads
  and moves into the rule's file. When they are one port file and no rule file, it is a type only that port and its
  adapters use and moves into the port's file. A class that no such file imports is not reported.
- PYRIGHT (with --pyright) counts pyright errors, using `[tool.pyright]` from the current folder.
"""

import argparse
import ast
import builtins
import io
import json
import re
import subprocess
import sys
import tokenize
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import override

LAYERS = ("a_domain", "b_application", "c_infrastructure", "d_presentation")
FORBIDDEN_LAYER_IMPORTS = {
    "a_domain": frozenset({"b_application", "c_infrastructure", "d_presentation"}),
    "b_application": frozenset({"c_infrastructure", "d_presentation"}),
    "c_infrastructure": frozenset({"d_presentation"}),
}
DOMAIN_FORBIDDEN_LIBRARIES = frozenset(
    {
        "aiohttp",
        "asyncpg",
        "bs4",
        "fastapi",
        "flet",
        "httpx",
        "lxml",
        "openai",
        "pandas",
        "pgvector",
        "requests",
        "shioaji",
        "sqlalchemy",
        "sqlite3",
        "starlette",
        "urllib3",
        "uvicorn",
        "yfinance",
    }
)
MAX_FUNCTION_LINES = 30
LOOP_INDEX_NAMES = frozenset({"i", "j", "k"})
ENUM_BASES = frozenset({"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag", "ReprEnum"})
VALUE_HOLDER_BASES = frozenset({"BaseModel", "RootModel", "SQLModel", "BaseSettings", "TypedDict", "NamedTuple"})
BUILTIN_EXCEPTIONS = frozenset(
    name for name, value in vars(builtins).items() if isinstance(value, type) and issubclass(value, BaseException)
)
FACTORY_MODULE = PurePosixPath("d_presentation/dependencies.py")
FACTORY_TARGETS = ("c_infrastructure", "b_application.use_cases", "b_application.pipeline")
PRESENTATION_SETTINGS = {
    # The runtime switch compares the revisions a runtime was built from with the files on disk and bounds how long the
    # startup on new settings may take. The Web API's timers look at the settings files, archive the open data and read
    # the world's feeds at the current settings' intervals.
    "d_presentation/live_runtime.py": frozenset(
        {
            "settings_revisions",
            "api.settings_build_timeout_seconds",
            "api.settings_poll_seconds",
            "api.archive_interval_hours",
            "api.world_interval_minutes",
        }
    ),
    # The settings editor shows the environment the server started in, read-only: a save cannot change it.
    "d_presentation/web/routers/admin.py": frozenset({"environment"}),
    # The brokers endpoint names, for a run's confirmation, the server a real broker trades on and its BUY limits, so
    # the user confirms SinoPac's simulation or real account and the limits the order gates will hold the run to. The
    # SinoPac page shows the server and the simulation account's starting cash, which its panel switches through the
    # settings save.
    "d_presentation/web/routers/account.py": frozenset(
        {"shioaji.server", "shioaji.simulation_initial_cash", "trading.max_order_value", "trading.max_daily_buy_value"}
    ),
    # The Web's request gates: the host names it answers, and the audience's realtime quotes and MOPS, which decide which
    # runs and valuations a browser may start. A run starts under the cap of background runs of the runtime it starts on,
    # and a backtest takes its turn under the caps of replays. Whom the site shows each feature to gates the feature's
    # routes here, in front of the Pipeline, and tells the web app what to hide. A run on a real broker starts only on
    # the server its confirmation showed, the one shioaji.server names in the runtime it starts on.
    "d_presentation/web/session.py": frozenset(
        {
            "features",
            "shioaji.server",
            "api.allowed_hosts",
            "audience.realtime_quotes",
            "audience.mops",
            "accounts.max_concurrent_runs",
            "accounts.max_concurrent_backtests",
            "accounts.max_backtests_per_user",
        }
    ),
    # The Web API's timer of the scheduled ranking follows looks at the current settings' interval, and starts each
    # follow under the cap of background runs of the runtime it starts on, as a request's run starts.
    "d_presentation/web/scheduled_follows.py": frozenset({"api.follow_schedule_poll_seconds", "accounts.max_concurrent_runs"}),
    # The app serves the API docs only where the environment it started in allows them.
    "d_presentation/web/app.py": frozenset({"environment.api_docs"}),
    # The open data's attribution, which the license requires next to whatever a page shows from it, and the audience,
    # whose capabilities tell the web app what to offer.
    "d_presentation/web/routers/market.py": frozenset({"sources.attribution", "audience"}),
    "d_presentation/web": frozenset(
        {
            # The LINE webhook checks each request's signature with the channel secret.
            "line.channel_secret",
            # The built-in-strategies endpoint lists the strategies that ship in config/strategies.
            "technical.built_in_strategies",
        }
    ),
    # The menu prints the environment, and before a run on a real broker the server it trades on and the BUY limits the
    # order gates hold it to, so the user sees whether an order would reach a real account; it refuses what orders on
    # realtime quotes where the audience has none. Menus 5 and 6 print how undervaluation is computed, its caveat and
    # when a close turns stale.
    "d_presentation/cli": frozenset(
        {
            "environment",
            "audience",
            # The menu's header and a run's broker panel name the SinoPac server the site's login is on.
            "shioaji.server",
            "trading.max_order_value",
            "trading.max_daily_buy_value",
            "valuation.undervaluation_formula",
            "valuation.low_pe_caveat",
            "freshness.daily_close_max_missed_sessions",
            # The load-built-in-strategy menu lists the built-in strategies to choose from.
            "technical.built_in_strategies",
        }
    ),
}
RESPONSE_MODULE = PurePosixPath("d_presentation/web/schemas.py")
PIPELINE_MODULE = PurePosixPath("b_application/pipeline.py")
LOGGING_PORT = "a_domain.ports.system.logging_provider.ILoggingProvider"
PYDANTIC_DATACLASS = "pydantic.dataclasses.dataclass"
DOMAIN_CLASS_FOLDERS = ("a_domain/model", "a_domain/rules")
DOMAIN_FORBIDDEN_BASES = frozenset({"BaseModel", "RootModel", "SQLModel"})
CONSTANT_FREE_FOLDERS = ("a_domain", "b_application/use_cases", "b_application/schemas", "b_application/pipeline.py")
TYPE_FACTORIES = frozenset({"NewType", "TypeVar"})
CONSTANT_HOMES = "a fixed name is a StrEnum member in enums.py, an alias a type statement, any other value a setting"
NOT_CALLED = frozenset({"property", "model_validator", "field_validator"})
RULE_USERS = ("a_domain/rules", "a_domain/ports", "b_application/use_cases", "b_application/config")
RULE_CALLER_SCOPE = ("a_domain", "b_application", "d_presentation/dependencies.py")
COLLECTION_MUTATORS = frozenset(
    {"append", "extend", "insert", "add", "update", "discard", "remove", "pop", "popitem", "clear", "setdefault"}
)
STRATEGY_CLASSES = frozenset({"TechnicalStrategy", "TechnicalRule"})
COPY_SCOPE = ("a_domain/model", "b_application/schemas")
COPY_SHARE = 0.8
PORT_CALLERS_EXEMPT = frozenset(
    {
        ("ITaiwanStockProvider", "cached_stocks"),
        ("ICachedPriceProvider", "sync_index"),
        ("ICachedPriceProvider", "sync_references"),
        ("IFundamentalsProvider", "fetch_page"),
        ("ISocialMediaProvider", "fetch_tag_articles"),
        ("IBrokerExecutionProvider", "send"),
        ("IAttemptLog", "record"),
    }
)
"""
Port methods that only their own adapter calls, left on the port until the owner rules on them. Each but the last is
a step of one of its adapter's port methods that reads or writes most of what the adapter holds, its locks, its
cached state, its source, the database and the clock: as a module-level function it would take eight to ten
arguments, or the adapter itself. ICachedPriceProvider.sync_session, IBrokerExecutionProvider.place and
ISimulatedExecutionProvider.fill are steps of the same kind, which the name match does not report: another file
reads the same name on something else. IAttemptLog.record is the log's one write, which admit makes under each key;
the attempt-log tests pin its windows and its sweep through it.
"""
INFRASTRUCTURE_RULES = {
    # The port promises each post's stance, whatever model reads it. The prompt and the reply's contract are how the
    # AI provider this adapter asks gives one; a classifier that asks no AI would need neither.
    "c_infrastructure/ai_models/sentiment_classifier.py": frozenset({"SentimentPromptBuilder", "parse_sentiment_reply"}),
    # The tables store the owner's strategies, which are these classes: fields that carry their own apply. The DTO
    # builds and reads them and never calls apply.
    "c_infrastructure/database/models/technical_settings_dto.py": frozenset({"TechnicalScoring", "TechnicalStrategy"}),
    # The archive saves each bar as its exchange listed it. The port promises the adjusted history, computed on read
    # by the rule (guide 5), and the listed history as the ranking reads it.
    "c_infrastructure/database/repositories/daily_close_archive.py": frozenset({"HistoryAdjustmentRule", "ListedHistoryRule"}),
    # The same promise as the archive's, over the cached sessions: the adjusted history and the listed history.
    "c_infrastructure/market/cached_price_provider.py": frozenset({"HistoryAdjustmentRule", "ex_right_matrix"}),
    # The port promises the bars as one matrix, the ranking's history and a formula's replay of that history, each
    # built once from what the stores hold and kept until the stores change. The rules build them, and this adapter is
    # where they are kept.
    "c_infrastructure/market/daily_bar_matrix_provider.py": frozenset(
        {"DailyBarMatrixRule", "RankingHistoryRule", "RankingBacktestRule"}
    ),
    # The port promises a quarter's EPS page, fetched again only while it may still change. Whether a held page is
    # final is the rule's answer, asked here, where the page is held.
    "c_infrastructure/market/mops_fundamentals_provider.py": frozenset({"FilingDeadlineRule", "FinalFilingsRule"}),
    # The port promises admission: each attempt recorded and judged against its limit in one step, so two attempts
    # cannot both pass a limit that has room for one. The port's own signature names the rule.
    "c_infrastructure/system/attempt_log.py": frozenset({"AttemptLimitRule"}),
    # The simulated broker promises what an exchange would do with the order: whether it accepts it and what fills.
    "c_infrastructure/trading/mock/mock_execution_provider.py": frozenset({"FillRule", "OrderAcceptanceRule"}),
    # The SinoPac adapter promises the domain order's outcome: it refuses what the app never sends before any request,
    # splits the order into the exchange orders the broker takes, and reads their reports back into fills and costs.
    # It also promises the account's cash, which its own acceptance checks each order against: on the simulation
    # server, which reports none, that cash is the rule's figure from what the adapter reads of the account.
    "c_infrastructure/trading/shioaji/execution_provider.py": frozenset(
        {"BrokerOutcomeRule", "FillRule", "LotSplitRule", "OrderAcceptanceRule", "SimulationCashRule", "TradingCostRule"}
    ),
}
ANSWER_SOURCES = ("a_domain/model", "a_domain/types", "a_domain/ports")
MODEL_USERS = ("a_domain", "b_application", "d_presentation")
STORY_ID = re.compile(r"\bUS-\d+|\bTODO\b|(?<![\w&])#\d+\b")
TYPE_IGNORE = re.compile(r"#\s*(?:type|pyright)\s*:\s*ignore\b")
CJK = re.compile(
    r"[\u3000-\u303f\u3040-\u30ff\u3100-\u312f\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff"
    r"\uac00-\ud7af\uf900-\ufaff\uff00-\uffef\U00020000-\U0002fa1f]+"
)
URL = re.compile(r"https?://\S*", re.IGNORECASE)

type Finding = tuple[Path, int, str]
type FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True, order=True)
class Violation:
    path: str
    line: int
    rule: str
    message: str

    @override
    def __str__(self) -> str:
        return f"{self.rule} {self.path}:{self.line} {self.message}"


@dataclass(frozen=True)
class SourceFile:
    path: Path
    root: Path | None
    module: PurePosixPath | None
    tree: ast.Module
    text: str
    comments: tuple[tuple[int, str], ...]

    @property
    def layer(self) -> str | None:
        return self.module.parts[0] if self.module else None

    def under(self, folder: str) -> bool:
        return self.module is not None and self.module.is_relative_to(folder)

    def is_module(self, module: str) -> bool:
        return self.module == PurePosixPath(module)


def display(path: Path) -> str:
    absolute, cwd = path.resolve(), Path.cwd().resolve()
    return (absolute.relative_to(cwd) if absolute.is_relative_to(cwd) else absolute).as_posix()


def discover(paths: Sequence[Path]) -> list[Path]:
    found: set[Path] = set()
    for path in paths:
        if path.is_file():
            found.add(path)
            continue
        for candidate in path.rglob("*.py"):
            skipped = any(part.startswith(".") or part == "__pycache__" for part in candidate.relative_to(path).parts)
            if not skipped:
                found.add(candidate)
    return sorted(found)


def locate(path: Path) -> tuple[Path | None, PurePosixPath | None]:
    parts = path.resolve().parts
    for index, part in enumerate(parts):
        if part in LAYERS:
            return Path(*parts[:index]), PurePosixPath(*parts[index:])
    return None, None


def parse(path: Path) -> SourceFile:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    comments = tuple((token.start[0], token.string) for token in tokens if token.type == tokenize.COMMENT)
    root, module = locate(path)
    return SourceFile(path, root, module, tree, text, comments)


def name_of(expression: ast.expr) -> str | None:
    match expression:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case ast.Subscript(value=inner) | ast.Call(func=inner):
            return name_of(inner)
    return None


def base_names(node: ast.ClassDef) -> set[str]:
    return {name for base in node.bases if (name := name_of(base))}


def top_level_classes(tree: ast.Module) -> list[ast.ClassDef]:
    return [node for node in tree.body if isinstance(node, ast.ClassDef)]


def all_classes(tree: ast.Module) -> list[ast.ClassDef]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]


def methods(node: ast.ClassDef) -> list[FunctionNode]:
    return [item for item in node.body if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)]


def functions(tree: ast.Module) -> list[FunctionNode]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]


def docstring_of(node: ast.AST) -> ast.Constant | None:
    if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) or not node.body:
        return None
    first = node.body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return first.value
    return None


def docstrings(tree: ast.Module) -> list[ast.Constant]:
    return [docstring for node in ast.walk(tree) if (docstring := docstring_of(node))]


def subclass_names(files: Sequence[SourceFile], is_seed: Callable[[str], bool]) -> frozenset[str]:
    classes = [node for source in files for node in all_classes(source.tree)]
    known: set[str] = set()
    while grown := {
        node.name for node in classes if node.name not in known and any(is_seed(base) or base in known for base in base_names(node))
    }:
        known |= grown
    return frozenset(known)


def exception_names(files: Sequence[SourceFile]) -> frozenset[str]:
    return subclass_names(files, lambda base: base in BUILTIN_EXCEPTIONS or base.endswith(("Error", "Exception")))


def without_src(module: str) -> str:
    return module.removeprefix("src.")


def imported_from(source: SourceFile, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return without_src(node.module or "")
    if source.module is None:
        return None
    package = source.module.parent.parts
    keep = len(package) - (node.level - 1)
    if keep < 0:
        return None
    return ".".join([*package[:keep], *([node.module] if node.module else [])])


def imports(source: SourceFile) -> Iterator[tuple[int, str, tuple[str, ...]]]:
    for node in ast.walk(source.tree):
        if isinstance(node, ast.Import):
            yield from ((node.lineno, without_src(alias.name), ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and (module := imported_from(source, node)):
            yield node.lineno, module, tuple(alias.name for alias in node.names)


def bound_imports(source: SourceFile) -> dict[str, str]:
    bound: dict[str, str] = {}
    for node in ast.walk(source.tree):
        if isinstance(node, ast.Import):
            bound |= {
                alias.asname or alias.name.split(".")[0]: alias.name if alias.asname else alias.name.split(".")[0]
                for alias in node.names
            }
        elif isinstance(node, ast.ImportFrom) and (module := imported_from(source, node)):
            bound |= {alias.asname or alias.name: f"{module}.{alias.name}" for alias in node.names}
    return bound


def is_within(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


def check_layer(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        forbidden = FORBIDDEN_LAYER_IMPORTS.get(source.layer or "", frozenset())
        if source.layer == "a_domain":
            forbidden |= DOMAIN_FORBIDDEN_LIBRARIES
        for line, module, _ in imports(source):
            if module.split(".")[0] in forbidden:
                yield source.path, line, f"{source.layer} imports {module}"


def check_errors_location(files: Sequence[SourceFile]) -> Iterator[Finding]:
    exceptions = exception_names(files)
    for source in files:
        if not source.under("a_domain") or source.is_module("a_domain/types/errors.py"):
            continue
        for node in all_classes(source.tree):
            if node.name in exceptions:
                yield source.path, node.lineno, f"exception {node.name} belongs in a_domain/types/errors.py"


def check_enum_str(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        if not source.is_module("a_domain/types/enums.py"):
            continue
        for node in top_level_classes(source.tree):
            bases = base_names(node)
            if bases & ENUM_BASES and "StrEnum" not in bases:
                yield source.path, node.lineno, f"enum {node.name} is not a StrEnum"


def package_exports(init: Path) -> frozenset[str]:
    try:
        tree = ast.parse(init.read_text(encoding="utf-8"))
    except OSError, SyntaxError, ValueError:
        return frozenset()
    bound = {alias.asname or alias.name for node in tree.body if isinstance(node, ast.ImportFrom) for alias in node.names}
    bound |= {node.name for node in top_level_classes(tree)}
    listed = next((names for node in tree.body if (names := dunder_all(node)) is not None), None)
    return frozenset(bound if listed is None else bound & listed)


def dunder_all(node: ast.stmt) -> set[str] | None:
    if not (isinstance(node, ast.Assign) and any(name_of(target) == "__all__" for target in node.targets)):
        return None
    if not isinstance(node.value, ast.List | ast.Tuple):
        return None
    return {item.value for item in node.value.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)}


def check_port_protocol(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        if not source.under("a_domain/ports"):
            continue
        init = source.path.parent / "__init__.py"
        bound = bound_imports(source)
        for node in top_level_classes(source.tree):
            if PYDANTIC_DATACLASS in {resolved(decorator, bound) for decorator in node.decorator_list}:
                continue
            if "Protocol" not in base_names(node):
                yield source.path, node.lineno, f"port {node.name} is not a typing.Protocol"
            if not re.match(r"I[A-Z]", node.name):
                yield source.path, node.lineno, f"port {node.name} does not start with I"
            if node.name not in package_exports(init.resolve()):
                yield source.path, node.lineno, f"port {node.name} is not re-exported from {display(init)}"


def check_port_callers(files: Sequence[SourceFile]) -> Iterator[Finding]:
    read_names = {source.path: {node.attr for node in ast.walk(source.tree) if isinstance(node, ast.Attribute)} for source in files}
    for source in files:
        if not source.under("a_domain/ports"):
            continue
        for port in top_level_classes(source.tree):
            if "Protocol" not in base_names(port):
                continue
            called = names_read_outside(files, read_names, source.path, port.name)
            for method in methods(port):
                is_dunder = method.name.startswith("__") and method.name.endswith("__")
                if is_dunder or method.name in called or (port.name, method.name) in PORT_CALLERS_EXEMPT:
                    continue
                helper_home = "only its own adapter calls it; make it a module-level function beside the adapter"
                yield source.path, method.lineno, f"{port.name}.{method.name}: {helper_home}"


def names_read_outside(files: Sequence[SourceFile], read_names: Mapping[Path, set[str]], port_file: Path, port: str) -> set[str]:
    """Every attribute name read in a file that is neither the port's own nor one that defines a class descending from it."""
    family = subclass_names(files, lambda base: base == port)
    own = {port_file} | {source.path for source in files if any(node.name in family for node in all_classes(source.tree))}
    return {name for path, names in read_names.items() if path not in own for name in names}


def check_rule_apply(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        if not source.under("a_domain/rules"):
            continue
        for node in top_level_classes(source.tree):
            public = [
                method
                for method in methods(node)
                if not method.name.startswith("_") and not NOT_CALLED & {name_of(decorator) for decorator in method.decorator_list}
            ]
            if not public:
                continue
            if "apply" not in {method.name for method in public}:
                yield source.path, node.lineno, f"rule {node.name} has no apply method"
            for method in public:
                if method.name != "apply":
                    yield source.path, method.lineno, f"rule {node.name} exposes {method.name}; apply is a rule's only public method"


def check_usecase_execute(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        if not source.under("b_application/use_cases"):
            continue
        classes = top_level_classes(source.tree)
        for extra in classes[1:]:
            yield source.path, extra.lineno, f"{extra.name} shares a use case file with {classes[0].name}; one use case per file"
        for node in classes:
            yield from use_case_method_findings(source, node)
        for line, module, names in imports(source):
            if any(is_within(candidate, "b_application.use_cases") for candidate in [module, *(f"{module}.{name}" for name in names)]):
                yield source.path, line, f"imports {module}; use cases do not use each other, a workflow belongs in the Pipeline"


def use_case_method_findings(source: SourceFile, node: ast.ClassDef) -> Iterator[Finding]:
    if "execute" not in {method.name for method in methods(node)}:
        yield source.path, node.lineno, f"use case {node.name} has no execute method"
    for method in methods(node):
        if method.name not in {"__init__", "execute"}:
            yield source.path, method.lineno, f"use case {node.name} defines {method.name}; a use case has only __init__ and execute"


def check_one_pipeline(files: Sequence[SourceFile]) -> Iterator[Finding]:
    yield from single_class_findings(files, "Pipeline", "b_application/pipeline.py")
    yield from single_class_findings(files, "PipelineStatus", "b_application/schemas/pipeline_status.py")
    for source in files:
        if not source.under("b_application"):
            continue
        for node in all_classes(source.tree):
            if node.name.endswith("Pipeline") and node.name != "Pipeline":
                yield source.path, node.lineno, f"{node.name} is a second pipeline; workflows belong in the one Pipeline"


def single_class_findings(files: Sequence[SourceFile], class_name: str, home: str) -> Iterator[Finding]:
    roots_with_class: Counter[Path | None] = Counter()
    for source in files:
        for node in all_classes(source.tree):
            if node.name != class_name:
                continue
            if not source.is_module(home):
                yield source.path, node.lineno, f"{class_name} is defined outside {home}"
                continue
            roots_with_class[source.root] += 1
            if roots_with_class[source.root] > 1:
                yield source.path, node.lineno, f"second {class_name} in {home}; there is exactly one"
    scanned = {source.path.resolve() for source in files}
    for root in sorted({source.root for source in files if source.root and source.under("b_application")} - set(roots_with_class)):
        expected = root / home
        if expected in scanned or not expected.exists():
            yield expected, 1, f"there is no {class_name} class in {home}"


def check_settings_location(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        if source.under("b_application/config"):
            continue
        for node in all_classes(source.tree):
            if "BaseSettings" in base_names(node):
                yield source.path, node.lineno, f"settings class {node.name} belongs in b_application/config/"


def is_private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def check_private_method(files: Sequence[SourceFile]) -> Iterator[Finding]:
    homes = "make it a module-level function in this file, another rule, or a method of the model it is about"
    for source in files:
        for node in all_classes(source.tree):
            for method in methods(node):
                if is_private(method.name):
                    yield source.path, method.lineno, f"{node.name}.{method.name} is private; {homes}"


def check_infra_override(files: Sequence[SourceFile]) -> Iterator[Finding]:
    exempt = (
        exception_names(files)
        | subclass_names(files, lambda base: base in ENUM_BASES)
        | subclass_names(files, lambda base: base in VALUE_HOLDER_BASES)
    )
    for source in files:
        if not source.under("c_infrastructure") or source.under("c_infrastructure/database/models"):
            continue
        for node in top_level_classes(source.tree):
            if node.name in exempt or is_table_or_dataclass(node):
                continue
            for method in methods(node):
                if problem := override_problem(node, method):
                    yield source.path, method.lineno, problem


def is_table_or_dataclass(node: ast.ClassDef) -> bool:
    is_table = any(
        keyword.arg == "table" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True for keyword in node.keywords
    )
    return is_table or "dataclass" in {name_of(decorator) for decorator in node.decorator_list}


def override_problem(node: ast.ClassDef, method: FunctionNode) -> str | None:
    if method.name == "__init__" or is_private(method.name):
        return None
    if "override" not in {name_of(decorator) for decorator in method.decorator_list}:
        return f"{node.name}.{method.name} is not marked @override"
    return None


def check_factory_only(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        if source.under("c_infrastructure") or source.module == FACTORY_MODULE:
            continue
        bound = bound_imports(source)
        for node in ast.walk(source.tree):
            if not isinstance(node, ast.Call):
                continue
            target = called_class(node, bound)
            if target and any(is_within(target, package) for package in FACTORY_TARGETS):
                yield source.path, node.lineno, f"creates {target}; only {FACTORY_MODULE} creates adapters, use cases and the Pipeline"


def called_class(call: ast.Call, bound: dict[str, str]) -> str | None:
    parts = dotted(call.func)
    if not parts or parts[0] not in bound:
        return None
    name = parts[-1]
    if not name[0].isupper() or name.isupper():
        return None
    return without_src(".".join([bound[parts[0]], *parts[1:]]))


def dotted(expression: ast.expr) -> list[str] | None:
    if isinstance(expression, ast.Name):
        return [expression.id]
    if isinstance(expression, ast.Attribute) and (head := dotted(expression.value)):
        return [*head, expression.attr]
    return None


def check_presentation_decides_nothing(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        if not source.under("d_presentation") or source.module == FACTORY_MODULE:
            continue
        for line, module in rule_imports(source, annotations_allowed=True):
            yield source.path, line, f"imports {module}; the presentation calls the use case or workflow that runs the rule"
        yield from setting_read_findings(source)
        if source.module == RESPONSE_MODULE:
            for node in all_classes(source.tree):
                for method in methods(node):
                    yield (
                        source.path,
                        method.lineno,
                        f"response {node.name} defines {method.name}; a response maps fields and computes nothing",
                    )


def setting_read_findings(source: SourceFile) -> Iterator[Finding]:
    allowed = next((paths for folder, paths in PRESENTATION_SETTINGS.items() if source.under(folder)), frozenset())
    parents = {child: node for node in ast.walk(source.tree) for child in ast.iter_child_nodes(node)}
    for node in ast.walk(source.tree):
        if not isinstance(node, ast.Attribute) or name_of(node.value) != "config":
            continue
        path = setting_path(node, parents)
        if not any(path == entry or path.startswith(f"{entry}.") for entry in allowed):
            yield source.path, node.lineno, f"reads the setting {path}; a business setting reaches its rule through dependencies.py"


def setting_path(node: ast.Attribute, parents: dict[ast.AST, ast.AST]) -> str:
    path = [node.attr]
    while isinstance(parent := parents.get(node), ast.Attribute) and parent.value is node:
        path.append(parent.attr)
        node = parent
    return ".".join(path)


def check_strategy_from_settings(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        for node in ast.walk(source.tree):
            if isinstance(node, ast.Call) and (name := name_of(node.func)) in STRATEGY_CLASSES:
                yield (
                    source.path,
                    node.lineno,
                    f"builds {name}; strategies come from config/strategies/*.json or the owner's saved settings, "
                    "validated by pydantic",
                )


def function_length(function: FunctionNode) -> int:
    length = (function.end_lineno or function.lineno) - function.lineno + 1
    if docstring := docstring_of(function):
        length -= (docstring.end_lineno or docstring.lineno) - docstring.lineno + 1
    return length


def check_func_length(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        if source.module in (FACTORY_MODULE, PIPELINE_MODULE):
            continue
        executes = [
            method
            for node in source.tree.body
            if isinstance(node, ast.ClassDef) and source.under("b_application/use_cases")
            for method in node.body
            if isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef) and method.name == "execute"
        ]
        for function in functions(source.tree):
            length = function_length(function)
            if length > MAX_FUNCTION_LINES and function not in executes:
                yield source.path, function.lineno, f"{function.name} is {length} lines long (max {MAX_FUNCTION_LINES})"


def bound_names(tree: ast.Module) -> Iterator[tuple[ast.AST, str]]:
    for node in ast.walk(tree):
        match node:
            case ast.Name(id=name, ctx=ast.Store()) | ast.Attribute(attr=name, ctx=ast.Store()):
                yield node, name
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
                yield node, name
            case ast.arg(arg=name) | ast.ExceptHandler(name=str(name)) | ast.alias(asname=str(name)):
                yield node, name
            case ast.MatchAs(name=str(name)) | ast.MatchStar(name=str(name)) | ast.MatchMapping(rest=str(name)):
                yield node, name
            case ast.TypeVar(name=name) | ast.ParamSpec(name=name) | ast.TypeVarTuple(name=name):
                yield node, name


def loop_target_ids(tree: ast.Module) -> set[int]:
    targets = [node.target for node in ast.walk(tree) if isinstance(node, ast.For | ast.AsyncFor | ast.comprehension)]
    return {id(name) for target in targets for name in ast.walk(target) if isinstance(name, ast.Name)}


def check_names(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        loop_targets = loop_target_ids(source.tree)
        for node, name in bound_names(source.tree):
            allowed = name == "_" or (name in LOOP_INDEX_NAMES and id(node) in loop_targets)
            if len(name) == 1 and not allowed:
                yield source.path, getattr(node, "lineno", 1), f"single-letter name {name!r}"


def check_story_id(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        texts = [(line, text, "comment") for line, text in source.comments]
        texts += [(docstring.lineno, str(docstring.value), "docstring") for docstring in docstrings(source.tree)]
        for line, text, kind in texts:
            for match in STORY_ID.finditer(text):
                yield source.path, line + text[: match.start()].count("\n"), f"story or ticket id {match.group()!r} in a {kind}"


def check_type_ignore(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        for line, text in source.comments:
            if TYPE_IGNORE.search(text):
                yield source.path, line, "type checker suppression; fix the type error instead"


def check_english(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        for number, line in enumerate(source.text.split("\n"), start=1):
            if match := CJK.search(line):
                yield source.path, number, f"CJK text {match.group()!r}; write English, and keep data-format text in settings"


def check_hardcoded_url(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        skipped = {id(docstring) for docstring in docstrings(source.tree)}
        for node in ast.walk(source.tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str) or id(node) in skipped:
                continue
            if match := URL.search(node.value):
                yield source.path, node.lineno, f"hard-coded URL {match.group()[:80]!r}; URLs and hosts come from settings"


def check_future_import(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        for line, module, _ in imports(source):
            if module == "__future__":
                yield (
                    source.path,
                    line,
                    "from __future__ import; Python 3.14 evaluates annotations lazily, and Self names the own class",
                )


def resolved(expression: ast.expr, bound: dict[str, str]) -> str | None:
    parts = dotted(expression.func if isinstance(expression, ast.Call) else expression)
    if not parts:
        return None
    return ".".join([bound.get(parts[0], parts[0]), *parts[1:]])


def is_exempt_domain_class(node: ast.ClassDef, exceptions: frozenset[str]) -> bool:
    bases = base_names(node)
    return node.name in exceptions or bool(bases & ENUM_BASES) or "Protocol" in bases


def check_model_copy(files: Sequence[SourceFile]) -> Iterator[Finding]:
    classes = [
        (source, node)
        for source in files
        if any(source.under(folder) for folder in COPY_SCOPE)
        for node in top_level_classes(source.tree)
    ]
    models = [(node, field_names(node) | property_names(node)) for source, node in classes if source.under("a_domain/model")]
    for source, node in classes:
        fields = field_names(node)
        if len(fields) < 2:
            continue
        if original := next(
            (other for other, names in models if other is not node and len(fields & names) >= COPY_SHARE * len(fields)), None
        ):
            yield (
                source.path,
                node.lineno,
                f"{node.name} copies the fields of {original.name}; use {original.name} itself, and let a DTO or a "
                f"response hold only what {original.name} lacks or must hide",
            )
    yield from response_copies(files)


def response_copies(files: Sequence[SourceFile]) -> Iterator[Finding]:
    domain = [
        node for source in files if any(source.under(folder) for folder in ANSWER_SOURCES) for node in top_level_classes(source.tree)
    ]
    for source in files:
        if source.module != RESPONSE_MODULE:
            continue
        local = module_names(source.tree)
        for node in top_level_classes(source.tree):
            fields = field_names(node)
            if len(fields) < 2 or annotation_names(node) & local:
                continue
            if original := next((other for other in domain if field_names(other) == fields), None):
                yield (
                    source.path,
                    node.lineno,
                    f"{node.name} copies every field of {original.name}; answer with {original.name} itself",
                )


def module_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        match node:
            case ast.ClassDef(name=name) | ast.TypeAlias(name=ast.Name(id=name)) | ast.Assign(targets=[ast.Name(id=name)]):
                names.add(name)
    return names


def annotation_names(node: ast.ClassDef) -> set[str]:
    return {
        name.id
        for item in node.body
        if isinstance(item, ast.AnnAssign)
        for name in ast.walk(item.annotation)
        if isinstance(name, ast.Name)
    }


def field_names(node: ast.ClassDef) -> set[str]:
    return {item.target.id for item in node.body if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)}


def property_names(node: ast.ClassDef) -> set[str]:
    return {
        method.name
        for method in methods(node)
        if {name_of(decorator) for decorator in method.decorator_list} & {"property", "cached_property"}
    }


def check_model_home(files: Sequence[SourceFile]) -> Iterator[Finding]:
    importers = name_importers(files)
    for source in files:
        if not source.under("a_domain/model") or source.module is None:
            continue
        module = ".".join(source.module.with_suffix("").parts)
        for node in top_level_classes(source.tree):
            if node.name in names_outside(source.tree, node):
                continue
            if home := model_home(importers.get(f"{module}.{node.name}", set())):
                yield source.path, node.lineno, f"{node.name} {home}"


def name_importers(files: Sequence[SourceFile]) -> dict[str, set[PurePosixPath]]:
    """Each name a file of MODEL_USERS imports with `from module import name`, as `module.name`, and those files."""
    importers: dict[str, set[PurePosixPath]] = {}
    for source in files:
        if source.module is None or source.layer not in MODEL_USERS:
            continue
        for _, module, names in imports(source):
            for name in names:
                importers.setdefault(f"{module}.{name}", set()).add(source.module)
    return importers


def names_outside(tree: ast.Module, node: ast.ClassDef) -> set[str]:
    """Every name the module reads or writes outside the class `node`, its decorators included."""
    inside = {id(child) for child in ast.walk(node)}
    return {name.id for name in ast.walk(tree) if isinstance(name, ast.Name) and id(name) not in inside}


def model_home(importers: set[PurePosixPath]) -> str | None:
    """Where a model class goes when one rule, or one port, is all that imports it; None while it is a shared model."""
    rules = sorted(path for path in importers if path.is_relative_to("a_domain/rules"))
    ports = sorted(path for path in importers if path.is_relative_to("a_domain/ports"))
    if len(rules) + len(ports) < len(importers):
        return None
    if len(rules) == 1:
        return f"is a value only the rule in {rules[0]} reads (a port may hand it over); move it into that rule's file"
    if not rules and len(ports) == 1:
        return f"is a type only the port in {ports[0]} and its adapters use; move it into that port's file"
    return None


def check_domain_style(files: Sequence[SourceFile]) -> Iterator[Finding]:
    exceptions = exception_names(files)
    for source in files:
        if not source.under("a_domain"):
            continue
        for line, module, names in imports(source):
            if module.split(".")[0] == "icontract":
                yield (
                    source.path,
                    line,
                    "imports icontract; the domain validates with Field, type aliases, model_validator and validate_call",
                )
            if module == "dataclasses" and "dataclass" in names:
                yield source.path, line, f"imports the standard dataclass; domain classes use {PYDANTIC_DATACLASS}"
        if any(source.under(folder) for folder in DOMAIN_CLASS_FOLDERS):
            yield from domain_class_findings(source, exceptions)


def domain_class_findings(source: SourceFile, exceptions: frozenset[str]) -> Iterator[Finding]:
    bound = bound_imports(source)
    for node in top_level_classes(source.tree):
        if is_exempt_domain_class(node, exceptions):
            continue
        if forbidden := base_names(node) & DOMAIN_FORBIDDEN_BASES:
            yield (
                source.path,
                node.lineno,
                f"{node.name} subclasses {', '.join(sorted(forbidden))}; SQLModel belongs to infrastructure tables",
            )
        if PYDANTIC_DATACLASS not in {resolved(decorator, bound) for decorator in node.decorator_list}:
            yield source.path, node.lineno, f"{node.name} is not a pydantic dataclass"
        for method in methods(node):
            if method.name == "__post_init__":
                yield (
                    source.path,
                    method.lineno,
                    f"{node.name}.__post_init__; a limit is a Field, a check across fields a model_validator",
                )


def is_constant(node: ast.stmt) -> str | None:
    if not isinstance(node, ast.Assign | ast.AnnAssign):
        return None
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names = [name for target in targets if (name := name_of(target)) and name != "__all__"]
    if not names or (isinstance(node.value, ast.Call) and name_of(node.value.func) in TYPE_FACTORIES):
        return None
    return names[0]


def check_module_constant(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        if not any(source.under(folder) for folder in CONSTANT_FREE_FOLDERS):
            continue
        for node in source.tree.body:
            if name := is_constant(node):
                yield source.path, node.lineno, f"module-level {name}; {CONSTANT_HOMES}"


def check_pipeline_fields(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        if source.module != PIPELINE_MODULE:
            continue
        bound = bound_imports(source)
        for node in top_level_classes(source.tree):
            if node.name != "Pipeline":
                yield source.path, node.lineno, f"{node.name} sits beside the Pipeline; the Pipeline's fields are its use cases"
                continue
            for field in node.body:
                if isinstance(field, ast.AnnAssign) and (problem := pipeline_field_problem(field, bound)):
                    yield source.path, field.lineno, problem


def pipeline_field_problem(field: ast.AnnAssign, bound: dict[str, str]) -> str | None:
    kind = resolved(field.annotation, bound) or ast.unparse(field.annotation)
    if kind == LOGGING_PORT or is_within(kind, "b_application.use_cases"):
        return None
    field_name, field_type = ast.unparse(field.target), ast.unparse(field.annotation)
    return f"Pipeline field {field_name} is {field_type}; the Pipeline holds only use cases and the logger"


def check_rule_callers(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        if source.under("c_infrastructure"):
            yield from infrastructure_rule_findings(source)
        if not any(source.under(folder) for folder in RULE_CALLER_SCOPE) or any(source.under(folder) for folder in RULE_USERS):
            continue
        for line, module in rule_imports(source, annotations_allowed=source.module == PIPELINE_MODULE):
            yield source.path, line, f"imports {module}; only use cases and other rules use a rule"


def infrastructure_rule_findings(source: SourceFile) -> Iterator[Finding]:
    allowed = INFRASTRUCTURE_RULES.get(source.module.as_posix() if source.module else "", frozenset())
    imported: set[str] = set()
    for line, module, names in imports(source):
        if not any(is_within(candidate, "a_domain.rules") for candidate in [module, *(f"{module}.{name}" for name in names)]):
            continue
        values = rule_values(source.root, module)
        imported |= set(names)
        for name in names or (module,):
            if name not in values and name not in allowed:
                yield (
                    source.path,
                    line,
                    f"imports the decision {name} of {module}; infrastructure carries data, and the use case that calls "
                    "the adapter runs the rule, unless INFRASTRUCTURE_RULES names it with its reason",
                )
    for name in sorted(allowed - imported):
        yield source.path, 1, f"INFRASTRUCTURE_RULES names {name}, which this file does not import"


def rule_values(root: Path | None, module: str) -> frozenset[str]:
    """The names a rule file defines at its top level that decide nothing: a class without `apply`, an alias, an assignment."""
    try:
        tree = ast.parse(((root or Path()) / f"{module.replace('.', '/')}.py").read_text(encoding="utf-8"))
    except OSError, SyntaxError, ValueError:
        return frozenset()
    deciding = {node.name for node in top_level_classes(tree) if "apply" in {method.name for method in methods(node)}}
    return frozenset(module_names(tree) - deciding)


def rule_imports(source: SourceFile, *, annotations_allowed: bool) -> Iterator[tuple[int, str]]:
    exempt = annotation_only_imports(source.tree) if annotations_allowed else set()
    for line, module, names in imports(source):
        if line in exempt:
            continue
        if any(is_within(candidate, "a_domain.rules") for candidate in [module, *(f"{module}.{name}" for name in names)]):
            yield line, module


def annotation_only_imports(tree: ast.Module) -> set[int]:
    """The lines of the `from` imports whose every name the file uses, and uses only inside annotations."""
    annotations = [annotation for node in ast.walk(tree) if (annotation := annotation_of(node))]
    inside = {id(node) for annotation in annotations for node in ast.walk(annotation)}
    names = [node for node in ast.walk(tree) if isinstance(node, ast.Name)]
    annotated = {name.id for name in names if id(name) in inside} - {name.id for name in names if id(name) not in inside}
    return {
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and all((alias.asname or alias.name) in annotated for alias in node.names)
    }


def annotation_of(node: ast.AST) -> ast.expr | None:
    match node:
        case (
            ast.arg(annotation=ast.expr() as annotation)
            | ast.AnnAssign(annotation=annotation)
            | ast.FunctionDef(returns=ast.expr() as annotation)
            | ast.AsyncFunctionDef(returns=ast.expr() as annotation)
        ):
            return annotation
    return None


def status_names(tree: ast.Module) -> set[str]:
    names = {"status"}
    for function in functions(tree):
        every = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
        names |= {argument.arg for argument in every if argument.annotation and name_of(argument.annotation) == "PipelineStatus"}
    return names


def written_status_field(target: ast.expr, names: set[str]) -> str | None:
    while isinstance(target, ast.Subscript):
        target = target.value
    parts = dotted(target)
    if not parts or parts[0] not in names or len(parts) < 2 or parts[1] == "stats":
        return None
    return ".".join(parts[:2])


def check_usecase_status(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        if not source.under("b_application/use_cases"):
            continue
        names = status_names(source.tree)
        for node in ast.walk(source.tree):
            for written in status_writes(node, names):
                yield source.path, node.lineno, f"writes {written}; a use case returns its result and adds only to status.stats"


def status_writes(node: ast.AST, names: set[str]) -> Iterator[str]:
    match node:
        case ast.Assign(targets=targets) | ast.Delete(targets=targets):
            yield from (field for target in targets if (field := written_status_field(target, names)))
        case ast.AugAssign(target=target) | ast.AnnAssign(target=target):
            if field := written_status_field(target, names):
                yield field
        case ast.Call(func=ast.Attribute() as function):
            parts = dotted(function) or []
            if len(parts) == 2 and parts[0] in names and not parts[1].startswith("require_"):
                yield ".".join(parts)
            if len(parts) > 2 and parts[0] in names and parts[1] != "stats" and parts[-1] in COLLECTION_MUTATORS:
                yield ".".join(parts[:2])


def check_path_comment(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        if source.module is None:
            continue
        for line, text in source.comments:
            if source.module.as_posix() in text:
                yield source.path, line, "comment repeats the file's path"


RULES: dict[str, Callable[[Sequence[SourceFile]], Iterator[Finding]]] = {
    "LAYER": check_layer,
    "ERRORS-LOCATION": check_errors_location,
    "ENUM-STR": check_enum_str,
    "PORT-PROTOCOL": check_port_protocol,
    "PORT-CALLERS": check_port_callers,
    "RULE-APPLY": check_rule_apply,
    "USECASE-EXECUTE": check_usecase_execute,
    "ONE-PIPELINE": check_one_pipeline,
    "SETTINGS-LOCATION": check_settings_location,
    "INFRA-OVERRIDE": check_infra_override,
    "PRIVATE-METHOD": check_private_method,
    "FACTORY-ONLY": check_factory_only,
    "PRESENTATION-DECIDES-NOTHING": check_presentation_decides_nothing,
    "STRATEGY-FROM-SETTINGS": check_strategy_from_settings,
    "FUNC-LENGTH": check_func_length,
    "NAMES": check_names,
    "STORY-ID": check_story_id,
    "TYPE-IGNORE": check_type_ignore,
    "ENGLISH": check_english,
    "HARDCODED-URL": check_hardcoded_url,
    "FUTURE-IMPORT": check_future_import,
    "DOMAIN-STYLE": check_domain_style,
    "MODULE-CONSTANT": check_module_constant,
    "PIPELINE-FIELDS": check_pipeline_fields,
    "RULE-CALLERS": check_rule_callers,
    "USECASE-STATUS": check_usecase_status,
    "PATH-COMMENT": check_path_comment,
    "MODEL-COPY": check_model_copy,
    "MODEL-HOME": check_model_home,
}


def check(paths: Sequence[Path]) -> list[Violation]:
    files: list[SourceFile] = []
    violations: list[Violation] = []
    for path in discover(paths):
        try:
            files.append(parse(path))
        except (SyntaxError, UnicodeDecodeError, ValueError) as error:
            violations.append(Violation(display(path), getattr(error, "lineno", None) or 1, "PARSE", f"cannot parse: {error}"))
    for rule, rule_check in RULES.items():
        violations += [Violation(display(path), line, rule, message) for path, line, message in rule_check(files)]
    return sorted(violations)


def run_pyright(paths: Sequence[Path]) -> list[Violation]:
    command = [sys.executable, "-m", "pyright", "--outputjson", "--pythonpath", sys.executable, *map(str, paths)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        print(f"pyright produced no report: {completed.stderr.strip() or completed.stdout.strip()}", file=sys.stderr)
        raise SystemExit(2) from None
    return sorted(
        Violation(
            display(Path(diagnostic["file"])),
            diagnostic["range"]["start"]["line"] + 1,
            "PYRIGHT",
            " ".join(f"{diagnostic['message']} ({diagnostic.get('rule', 'error')})".split()),
        )
        for diagnostic in report.get("generalDiagnostics", [])
        if diagnostic.get("severity") == "error"
    )


def summary(violations: Sequence[Violation], rules: Sequence[str]) -> list[str]:
    counts = Counter(violation.rule for violation in violations)
    width = max(len(rule) for rule in [*rules, "TOTAL"])
    rows = [f"  {rule:<{width}}  {counts[rule]:>5}" for rule in rules]
    return ["", "Violations per rule:", *rows, f"  {'TOTAL':<{width}}  {len(violations):>5}"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check backend code against docs/clean_architecture_guide.md.")
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("src")], help="files or folders to check (default: src)")
    parser.add_argument("--pyright", action="store_true", help="also run pyright and count its errors under PYRIGHT")
    arguments = parser.parse_args(argv)
    if missing := [str(path) for path in arguments.paths if not path.exists()]:
        parser.error(f"no such path: {', '.join(missing)}")
    violations = check(arguments.paths)
    rules = [*RULES, "PARSE"]
    if arguments.pyright:
        violations = sorted([*violations, *run_pyright(arguments.paths)])
        rules.append("PYRIGHT")
    for violation in violations:
        print(violation)
    print("\n".join(summary(violations, rules)))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
