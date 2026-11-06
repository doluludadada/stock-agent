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
  would hide the order of its steps. Cyclomatic complexity is ruff's C901, which checks both files.
- RULE-APPLY never counts a method decorated `@property`, so a rule may expose read-only values derived
  from its fields. A property's setter still counts. A method is public when its name does not start
  with `_`. A class with no public method is a value of the rule in its file. Every other class has
  `apply` and no other public method, static methods and class methods included. Dataclass fields are
  not methods.
- USECASE-EXECUTE allows only `__init__` and `execute`, and one class per use case file.
- INFRA-OVERRIDE lets `__init__` go unmarked, requires `@override` on every other public or dunder
  method, and forbids `_name` and `__name` methods. It skips DTOs (`table=True`, or any class under
  c_infrastructure/database/models/), enums, exceptions and value holders (`BaseModel`, `SQLModel`,
  `BaseSettings`, `TypedDict`, `NamedTuple`, `@dataclass`, and their subclasses).
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
  to PRESENTATION-DECIDES-NOTHING, and infrastructure is not checked.
- USECASE-STATUS treats `status`, and every parameter annotated `PipelineStatus`, as the run's status. Below
  b_application/use_cases it reports an assignment or deletion under any field but `stats`, a mutating collection
  method called on such a field, and a status method whose name does not start with `require_`.
- MODEL-COPY compares every class in a_domain/model and b_application/schemas that has at least two annotated fields
  with every class in a_domain/model. When at least 80% of its field names are fields or properties of another
  model, it copies that model, for storage, transport or a screen. Store, send and show the model itself; a DTO in
  c_infrastructure or a response in d_presentation holds only what the model lacks or must hide. Classes in
  a_domain/rules are not compared: sibling variants of one rule value share fields on purpose. COPY_EXEMPT names the
  classes left as they are, each with its reason. In d_presentation/web/schemas.py it reports only exact copies: a
  class whose field names are exactly those of a class in a_domain/model, a_domain/types or a_domain/ports, with no
  field typed by a name the module defines (another response, which hides part of a model, or PublicText, which
  redacts). A route answers with that domain class itself.
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
from collections.abc import Callable, Iterator, Sequence
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
        "aiosqlite",
        "asyncpg",
        "bs4",
        "chromadb",
        "fastapi",
        "flet",
        "httpx",
        "lxml",
        "openai",
        "pandas",
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
    # The runtime switch compares the revisions a runtime was built from with the files on disk, bounds how long the
    # startup on new settings may take, and starts every new runtime in the environment and the audience the process
    # started in. The Web API's timers look at the settings files and archive the open data at the current settings'
    # intervals.
    "d_presentation/live_runtime.py": frozenset(
        {
            "settings_revisions",
            "api.settings_build_timeout_seconds",
            "api.settings_poll_seconds",
            "api.archive_interval_hours",
            "environment",
            "audience",
        }
    ),
    # The settings editor shows the environment the server started in, read-only: a save cannot change it.
    "d_presentation/web/routers/admin.py": frozenset({"environment"}),
    # The account endpoint says whose account it shows, so the page never labels a Shioaji account as the mock one.
    "d_presentation/web/routers/account.py": frozenset({"trading.execution_provider", "trading.order_mode"}),
    # The Web's request gates: the host names it answers, and the broker and the audience's realtime quotes and MOPS,
    # which decide who may reach the private pages and which runs and valuations a browser may start. A run starts
    # under the cap of background runs of the runtime it starts on.
    "d_presentation/web/session.py": frozenset(
        {
            "api.allowed_hosts",
            "trading.execution_provider",
            "audience.realtime_quotes",
            "audience.mops",
            "accounts.max_concurrent_runs",
        }
    ),
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
    # The menu prints the trading setup, so the user sees whether an order would reach a real account, and refuses
    # what orders on realtime quotes where the audience has none. Menus 5 and 6 print how undervaluation is computed,
    # its caveat and when a close turns stale.
    "d_presentation/cli": frozenset(
        {
            "environment",
            "audience",
            "trading.execution_provider",
            "trading.order_mode",
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
RULE_USERS = ("a_domain/rules", "a_domain/ports", "b_application/use_cases", "b_application/config")
RULE_CALLER_SCOPE = ("a_domain", "b_application", "d_presentation/dependencies.py")
COLLECTION_MUTATORS = frozenset(
    {"append", "extend", "insert", "add", "update", "discard", "remove", "pop", "popitem", "clear", "setdefault"}
)
STRATEGY_CLASSES = frozenset({"TechnicalStrategy", "TechnicalRule"})
COPY_SCOPE = ("a_domain/model", "b_application/schemas")
COPY_SHARE = 0.8
COPY_EXEMPT = frozenset({"WebSearchResult"})
"""WebSearchResult belongs to the LINE chat, which stays unchanged until it is rebuilt as a customer-service bot."""
ANSWER_SOURCES = ("a_domain/model", "a_domain/types", "a_domain/ports")
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


def check_rule_apply(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        if not source.under("a_domain/rules"):
            continue
        for node in top_level_classes(source.tree):
            public = [
                method
                for method in methods(node)
                if not method.name.startswith("_") and "property" not in {name_of(decorator) for decorator in method.decorator_list}
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


def check_infra_override(files: Sequence[SourceFile]) -> Iterator[Finding]:
    exempt = (
        exception_names(files)
        | subclass_names(files, lambda base: base in ENUM_BASES)
        | subclass_names(files, lambda base: base in VALUE_HOLDER_BASES)
    )
    for source in files:
        if not source.under("c_infrastructure") or source.under("c_infrastructure/database/models"):
            continue
        for function in source.tree.body:
            if isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                yield source.path, function.lineno, f"{function.name} is a module-level helper; make it a public port method"
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
    name = method.name
    if name == "__init__":
        return None
    is_dunder = name.startswith("__") and name.endswith("__")
    if name.startswith("_") and not is_dunder:
        return f"{node.name}.{name} is private; adapter helpers are public port methods marked @override"
    if "override" not in {name_of(decorator) for decorator in method.decorator_list}:
        return f"{node.name}.{name} is not marked @override"
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
        for function in functions(source.tree):
            length = function_length(function)
            if length > MAX_FUNCTION_LINES:
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
        if len(fields) < 2 or node.name in COPY_EXEMPT:
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
        if not any(source.under(folder) for folder in RULE_CALLER_SCOPE) or any(source.under(folder) for folder in RULE_USERS):
            continue
        for line, module in rule_imports(source, annotations_allowed=source.module == PIPELINE_MODULE):
            yield source.path, line, f"imports {module}; only use cases and other rules use a rule"


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
    "RULE-APPLY": check_rule_apply,
    "USECASE-EXECUTE": check_usecase_execute,
    "ONE-PIPELINE": check_one_pipeline,
    "SETTINGS-LOCATION": check_settings_location,
    "INFRA-OVERRIDE": check_infra_override,
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
