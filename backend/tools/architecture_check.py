"""Check backend source code against docs/clean_architecture_guide.md.

Run from backend/:

    uv run python tools/architecture_check.py [--pyright] [paths ...]

Paths default to `src`. The checker prints one line per violation as `RULE-ID path:line message`,
then the number of violations per rule. It exits 1 when any violation exists, 0 when there is none,
and 2 on bad usage. It reads files with `ast` and `tokenize` and imports no project code.

A file's layer is the first folder in its path named a_domain, b_application, c_infrastructure or
d_presentation. Rules that name a folder apply below that folder; the others apply to every file.

How the rules measure:
- FUNC-LENGTH counts physical lines from the `def` line (decorators excluded) to the last line of
  the body, minus the lines of the docstring. Blank lines and comments inside the body count. A
  nested function is measured on its own and also counts toward the function that holds it.
- COMPLEXITY is McCabe complexity counted the way ruff's C901 counts it: 1, plus 1 for each `if`,
  `elif`, `for`, `while`, `except`, `try ... else`, `case` and nested function. A last `case` that
  always matches is free. Boolean operators and comprehensions add nothing.
- RULE-APPLY treats every method whose name does not start with `_` as public, properties, static
  methods and class methods included. Dataclass fields are not methods.
- USECASE-EXECUTE allows only `__init__` and `execute`, and one class per use case file.
- INFRA-OVERRIDE lets `__init__` go unmarked, requires `@override` on every other public or dunder
  method, and forbids `_name` and `__name` methods. It skips DTOs (`table=True`, or any class under
  c_infrastructure/database/models/), enums, exceptions and value holders (`BaseModel`, `SQLModel`,
  `BaseSettings`, `TypedDict`, `NamedTuple`, `@dataclass`, and their subclasses).
- FACTORY-ONLY treats a called name that starts with an upper-case letter as a class.
- PRESENTATION-DECIDES-NOTHING checks d_presentation except dependencies.py. A setting read is an attribute chain
  on a name or attribute called `config`, such as `runtime.config.line.channel_secret`. The chain must equal or
  extend an entry of PRESENTATION_SETTINGS for the file's folder; a file in no listed folder may read none. Every
  class in d_presentation/web/schemas.py must define no method.
- STRATEGY-FROM-SETTINGS treats a call whose called name is TechnicalStrategy or TechnicalRule as building one.
- STORY-ID looks for `US-<number>`, any to-do marker and `#<number>` in comments and docstrings.
- HARDCODED-URL ignores docstrings.
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
MAX_COMPLEXITY = 10
LOOP_INDEX_NAMES = frozenset({"i", "j", "k"})
ENUM_BASES = frozenset({"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag", "ReprEnum"})
VALUE_HOLDER_BASES = frozenset({"BaseModel", "RootModel", "SQLModel", "BaseSettings", "TypedDict", "NamedTuple"})
BUILTIN_EXCEPTIONS = frozenset(
    name for name, value in vars(builtins).items() if isinstance(value, type) and issubclass(value, BaseException)
)
FACTORY_MODULE = PurePosixPath("d_presentation/dependencies.py")
FACTORY_TARGETS = ("c_infrastructure", "b_application.use_cases", "b_application.pipeline")
PRESENTATION_SETTINGS = {
    # The LINE webhook checks each request's signature with the channel secret.
    "d_presentation/web": frozenset({"line.channel_secret"}),
    # The menu prints the trading setup, so the user sees whether an order would reach a real account.
    "d_presentation/cli": frozenset(
        {"environment", "trading.execution_provider", "trading.order_mode", "mock_trading.account_id", "shioaji.simulation"}
    ),
}
RESPONSE_MODULE = PurePosixPath("d_presentation/web/schemas.py")
STRATEGY_CLASSES = frozenset({"TechnicalStrategy", "TechnicalRule"})
STRATEGY_BUILDER = PurePosixPath("c_infrastructure/technical/technical_settings_schema.py")
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


def check_model_one_class(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        if not source.under("a_domain/model") or source.path.name == "__init__.py":
            continue
        classes = top_level_classes(source.tree)
        if not classes:
            yield source.path, 1, "model file defines no class; one class per model file"
        for extra in classes[1:]:
            yield source.path, extra.lineno, f"{extra.name} shares a model file with {classes[0].name}; one class per model file"


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
        for node in top_level_classes(source.tree):
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
            public = [method for method in methods(node) if not method.name.startswith("_")]
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
        for line, module, names in imports(source):
            if any(is_within(candidate, "a_domain.rules") for candidate in [module, *(f"{module}.{name}" for name in names)]):
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
        if source.module == STRATEGY_BUILDER:
            continue
        for node in ast.walk(source.tree):
            if isinstance(node, ast.Call) and (name := name_of(node.func)) in STRATEGY_CLASSES:
                yield source.path, node.lineno, f"builds {name}; strategies come from config/technical.yaml through {STRATEGY_BUILDER}"


def function_length(function: FunctionNode) -> int:
    length = (function.end_lineno or function.lineno) - function.lineno + 1
    if docstring := docstring_of(function):
        length -= (docstring.end_lineno or docstring.lineno) - docstring.lineno + 1
    return length


def check_func_length(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        for function in functions(source.tree):
            length = function_length(function)
            if length > MAX_FUNCTION_LINES:
                yield source.path, function.lineno, f"{function.name} is {length} lines long (max {MAX_FUNCTION_LINES})"


def branch_count(statements: Sequence[ast.stmt]) -> int:
    return sum(statement_branches(statement) for statement in statements)


def statement_branches(statement: ast.stmt) -> int:
    match statement:
        case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
            return 1 + branch_count(statement.body) + branch_count(statement.orelse)
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            return 1 + branch_count(statement.body)
        case ast.With() | ast.AsyncWith() | ast.ClassDef():
            return branch_count(statement.body)
        case ast.Try() | ast.TryStar():
            handlers = sum(1 + branch_count(handler.body) for handler in statement.handlers)
            else_branch = 1 if statement.orelse else 0
            return handlers + else_branch + sum(map(branch_count, (statement.body, statement.orelse, statement.finalbody)))
        case ast.Match():
            cases = sum(1 + branch_count(case.body) for case in statement.cases)
            last = statement.cases[-1]
            return cases - 1 if last.guard is None and always_matches(last.pattern) else cases
    return 0


def always_matches(pattern: ast.pattern) -> bool:
    if isinstance(pattern, ast.MatchAs):
        return pattern.pattern is None or always_matches(pattern.pattern)
    if isinstance(pattern, ast.MatchOr):
        return any(always_matches(option) for option in pattern.patterns)
    return False


def check_complexity(files: Sequence[SourceFile]) -> Iterator[Finding]:
    for source in files:
        for function in functions(source.tree):
            complexity = 1 + branch_count(function.body)
            if complexity > MAX_COMPLEXITY:
                yield source.path, function.lineno, f"{function.name} has cyclomatic complexity {complexity} (max {MAX_COMPLEXITY})"


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


RULES: dict[str, Callable[[Sequence[SourceFile]], Iterator[Finding]]] = {
    "LAYER": check_layer,
    "MODEL-ONE-CLASS": check_model_one_class,
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
    "COMPLEXITY": check_complexity,
    "NAMES": check_names,
    "STORY-ID": check_story_id,
    "TYPE-IGNORE": check_type_ignore,
    "ENGLISH": check_english,
    "HARDCODED-URL": check_hardcoded_url,
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
