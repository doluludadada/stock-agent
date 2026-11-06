"""
How the CLI and the Web API load their settings at startup, and refuse an unsafe trading setup. The administrator's
settings editor validates a candidate file through the same functions, so a saved file is one the app starts with, and
its form writes a setting into the text through them too.
"""

import hashlib
import json
import sys
from base64 import urlsafe_b64decode
from collections.abc import Iterator, Mapping, Sequence
from functools import cache
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin, override

import yaml
from pydantic import BaseModel, SecretStr, TypeAdapter, ValidationError
from pydantic.json_schema import GenerateJsonSchema
from pydantic_core import core_schema

from a_domain.ports.system.settings_files import SettingChange, SettingsProblem, SettingValue
from a_domain.types.enums import Audience, ExecutionProvider, InstructionKey, OrderMode, SettingsFile, SystemEnvironment
from a_domain.types.errors import SettingsEditError
from a_domain.types.values import FormulaId
from b_application.config.app_config import AppConfig


def get_project_root() -> Path:
    """The nearest folder above this file that holds the justfile or .git: config/, .env and stock_agent.db live there."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "justfile").exists() or (parent / ".git").exists():
            return parent

    raise FileNotFoundError("Could not find project root.")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    with path.open(encoding="utf-8") as config_file:
        return yaml.safe_load(config_file) or {}


def settings_revision(text: str) -> str:
    """A settings file's revision: the SHA-256 of its UTF-8 text, so any edit, by any editor, changes it."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def settings_text(project_root: Path, file: SettingsFile) -> str:
    path = project_root / "config" / file.file_name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def settings_texts(project_root: Path, candidates: Mapping[SettingsFile, str] | None = None) -> dict[SettingsFile, str]:
    """
    Every settings file's text: the candidate's where one is given, else the file's on disk, read only then, and empty
    when it is missing.
    """
    candidates = candidates or {}
    return {file: candidates[file] if file in candidates else settings_text(project_root, file) for file in SettingsFile}


def inject_prompt_settings(settings: dict[str, Any], instructions: dict[str, Any]) -> None:
    """Copies the AI prompts of config/instructions.yaml into the settings each InstructionKey names."""
    if not instructions:
        return

    for key in InstructionKey:
        section, name = key.settings_path.split(".")

        if isinstance(target := settings.setdefault(section, {}), dict):
            target[name] = instructions.get(key.value)


def inject_built_in_strategies(settings: dict[str, Any], strategies_folder: Path, texts: Mapping[SettingsFile, str]) -> None:
    """
    Replaces each id in technical.built_in_strategies with its config/strategies/<id>.json; AppConfig validates them.
    InvalidSettingsError at each id that cannot be read, saying why in words, never with a path of the server.
    """
    technical = settings.get("technical")

    if not isinstance(technical, dict) or not isinstance(ids := technical.get("built_in_strategies", []), list):
        return

    strategies, problems = [], []

    for index, strategy_id in enumerate(ids):
        try:
            strategies.append(read_built_in_strategy(strategies_folder, strategy_id))
        except ValueError as error:
            problems.append(locate(texts, f"technical.built_in_strategies.{index}", str(error)))

    if problems:
        raise InvalidSettingsError(problems)

    technical["built_in_strategies"] = strategies


def read_built_in_strategy(strategies_folder: Path, strategy_id: object) -> Any:
    """
    config/strategies/<id>.json, its id checked as a FormulaId before it names a path, so no id reaches another folder.
    ValueError in words, never an OSError's text: an id that is no strategy id, a file that is missing, or one that is not
    JSON.
    """
    try:
        TypeAdapter(FormulaId).validate_python(strategy_id)
    except ValidationError:
        raise ValueError("is not a built-in strategy id: lowercase letters, digits and underscores") from None

    path = strategies_folder / f"{strategy_id}.json"

    if not path.is_file():
        raise ValueError("names no built-in strategy in config/strategies")

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        raise ValueError(f"config/strategies/{strategy_id}.json cannot be read as JSON") from None


def load_settings(project_root: Path, candidates: Mapping[SettingsFile, str] | None = None) -> AppConfig:
    """
    config/appsetting.yaml with the prompts of config/instructions.yaml and the built-in strategies of
    config/strategies/, the secrets from .env, and each file's revision: the settings this process runs on. A
    candidate text stands in for its file, so the administrator's edit and a reload are validated by this same load,
    and only the texts it is given: nothing is filled in from the file on disk.

    Raises InvalidSettingsError, every problem located (SettingsProblem): a file that does not parse, at the parser's
    mark; a key that names no setting, or a setting the environment owns, which is refused so a secret can never be
    written into a settings file; a value the settings refuse, at its key or the nearest section above it.
    """
    texts = settings_texts(project_root, candidates)
    documents = {file: parsed_document(file, text) for file, text in texts.items()}

    if problems := unread_keys(documents, texts):
        raise InvalidSettingsError(problems)

    settings = documents[SettingsFile.APPSETTING]
    inject_prompt_settings(settings, documents[SettingsFile.INSTRUCTIONS])

    inject_built_in_strategies(settings, project_root / "config" / "strategies", texts)

    revisions = {file: settings_revision(text) for file, text in texts.items()}

    try:
        return AppConfig(project_root=project_root, settings_revisions=revisions, **settings)
    except ValidationError as error:
        located = [locate(texts, ".".join(str(part) for part in problem["loc"]), problem["msg"]) for problem in error.errors()]
        raise InvalidSettingsError(located) from None


def parsed_document(file: SettingsFile, text: str) -> dict[str, Any]:
    """
    The file's settings; InvalidSettingsError at the parser's mark when it does not parse or is not a mapping, and at the
    first anchor or alias: a settings file needs neither, and a few hundred bytes of aliases expand to millions of
    values, so they are refused from the parser's events, before anything expands them.
    """
    try:
        if (anchored := next((event for event in yaml.parse(text) if anchor_or_alias(event)), None)) is not None:
            mark = anchored.start_mark
            message = "YAML anchors and aliases are not allowed in a settings file"
            raise InvalidSettingsError([SettingsProblem(message=message, file=file, line=mark.line + 1, column=mark.column + 1)])

        document = yaml.safe_load(text)
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        line, column = (mark.line + 1, mark.column + 1) if mark else (None, None)
        raise InvalidSettingsError([SettingsProblem(message=f"YAML: {error.problem}", file=file, line=line, column=column)]) from None
    except yaml.YAMLError as error:
        raise InvalidSettingsError([SettingsProblem(message=f"YAML: {type(error).__name__}", file=file)]) from None

    if document is not None and not isinstance(document, dict):
        raise InvalidSettingsError([SettingsProblem(message="The file must map setting names to values", file=file, line=1, column=1)])

    return document or {}


def anchor_or_alias(event: yaml.Event) -> bool:
    return isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None) is not None


def unread_keys(documents: Mapping[SettingsFile, dict[str, Any]], texts: Mapping[SettingsFile, str]) -> list[SettingsProblem]:
    """
    Every key the app would not read: one that names no setting, one that names a setting the environment owns (a
    field with an environment alias: DB_PASSWORD under db, OPENAI_API_KEY under ai), and a prompt written anywhere but
    instructions.yaml. The settings come from AppConfig's own fields, recursively, never from a list kept by hand; a field
    the loader sets itself is marked `exclude` and names no setting either.
    """
    appsetting = [
        locate_in(texts, SettingsFile.APPSETTING, path.split("."), path, message)
        for path, message in unread_settings(documents[SettingsFile.APPSETTING], AppConfig, "")
    ]
    instructions = [
        locate_in(texts, SettingsFile.INSTRUCTIONS, [str(key)], str(key), "names no prompt of instructions.yaml")
        for key in documents[SettingsFile.INSTRUCTIONS]
        if key not in set(InstructionKey)
    ]
    return appsetting + instructions


def unread_settings(node: Mapping[Any, Any], model: type[BaseModel], prefix: str) -> Iterator[tuple[str, str]]:
    """(path, why) for each key of one section the settings would not read; sections are followed into their models."""
    fields = model.model_fields
    environment = {name for name, field in fields.items() if field.validation_alias is not None}
    environment |= {str(fields[name].validation_alias) for name in environment}
    prompts = {key.settings_path: key.value for key in InstructionKey}

    for key, value in node.items():
        path = f"{prefix}{key}"

        if key in environment:
            yield path, "comes from the environment or .env, never from a settings file"
        elif path in prompts:
            yield path, f"is the prompt {prompts[path]} of instructions.yaml"
        elif key not in fields or fields[key].exclude:
            yield path, "names no setting"
        elif isinstance(value, Mapping) and (section := section_model(fields[key].annotation)) is not None:
            yield from unread_settings(value, section, f"{path}.")


def section_model(annotation: Any) -> type[BaseModel] | None:
    """The settings model a field holds, alone or in an optional: a section whose keys are settings too."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation

    if isinstance(annotation, UnionType) or get_origin(annotation) is Union:
        return next((model for argument in get_args(annotation) if (model := section_model(argument)) is not None), None)

    return None


def locate(texts: Mapping[SettingsFile, str], path: str | None, message: str) -> SettingsProblem:
    """
    A problem about a setting, placed in the file that sets it: a prompt in instructions.yaml at its key, anything else in
    appsetting.yaml at the deepest key of its path the file has. A path no file sets (a value from .env, a default)
    keeps its path and gets no file.
    """
    if path is None:
        return SettingsProblem(message=message)

    prompt = next((key for key in InstructionKey if path == key.settings_path or path.startswith(f"{key.settings_path}.")), None)

    if prompt is not None:
        return locate_in(texts, SettingsFile.INSTRUCTIONS, [prompt.value], path, message)

    return locate_in(texts, SettingsFile.APPSETTING, path.split("."), path, message)


def locate_in(texts: Mapping[SettingsFile, str], file: SettingsFile, keys: list[str], path: str, message: str) -> SettingsProblem:
    """The problem at the start of the deepest of `keys` the file's YAML has, found with yaml.compose, which runs nothing."""
    try:
        node = yaml.compose(texts[file])
    except yaml.YAMLError:
        node = None

    mark = None

    for key in keys:
        child = child_node(node, key)

        if child is None:
            break

        mark, node = child[0].start_mark, child[1]

    if mark is None:
        return SettingsProblem(message=message, path=path)

    return SettingsProblem(message=message, file=file, path=path, line=mark.line + 1, column=mark.column + 1)


def child_node(node: yaml.Node | None, key: str) -> tuple[yaml.Node, yaml.Node] | None:
    """The (key, value) nodes of `key` in a mapping node, or (item, item) of the index `key` in a sequence node."""
    if isinstance(node, yaml.MappingNode):
        return next(((name, value) for name, value in node.value if name.value == key), None)

    if isinstance(node, yaml.SequenceNode) and key.isdigit() and int(key) < len(node.value):
        return node.value[int(key)], node.value[int(key)]

    return None


class SettingsFileSchema(GenerateJsonSchema):
    """
    The JSON schema of the settings classes as a settings file sets them, like unread_settings reads them: no field the
    environment owns (one with a validation alias, such as an API key) and no field the loader sets (`exclude`).
    """

    @override
    def field_is_present(
        self, field: core_schema.ModelField | core_schema.DataclassField | core_schema.TypedDictField | core_schema.ComputedField
    ) -> bool:
        return "validation_alias" not in field and not field.get("serialization_exclude") and super().field_is_present(field)


@cache
def settings_schema() -> dict[str, Any]:
    """What each setting of appsetting.yaml accepts, from the settings classes: its type, its choices, its bounds, its description."""
    return AppConfig.model_json_schema(schema_generator=SettingsFileSchema)


def with_changes(file: SettingsFile, text: str, changes: Sequence[SettingChange]) -> str:
    """
    `text` with each change written over its setting's value in place, as YAML the loader reads back as that value:
    every other character stays, comments and layout included. SettingsEditError, naming the setting but never a value,
    for a text that does not parse, a path that names no setting the text sets (a missing key or a section), a value of
    another kind than the one there, or a value that would not read back as written.
    """
    for change in changes:
        text = with_change(file, text, change)

    return text


def with_change(file: SettingsFile, text: str, change: SettingChange) -> str:
    path, document = ".".join(change.path), editable_document(file, text)
    section, key, node = section_of(document, change.path), change.path[-1], value_node(text, change.path)

    if section is None or key not in section or node is None or isinstance(node, yaml.MappingNode):
        raise SettingsEditError(f"{path} is not a setting {file.file_name} sets")

    if section[key] is not None and kind_of(section[key]) != kind_of(change.value):
        raise SettingsEditError(f"{path} holds a {kind_of(section[key])} in {file.file_name}, not a {kind_of(change.value)}")

    start, end = value_span(text, node)
    written = yaml_value(change.value)
    edited = text[:start] + (written if start < end else f" {written}") + text[end:]
    section[key] = change.value

    try:
        read_back = parsed_document(file, edited)
    except InvalidSettingsError:
        read_back = None

    if read_back != document:
        raise SettingsEditError(f"{path} cannot be written in place in {file.file_name}; change it in the text")

    return edited


def editable_document(file: SettingsFile, text: str) -> dict[str, Any]:
    try:
        return parsed_document(file, text)
    except InvalidSettingsError:
        raise SettingsEditError(f"{file.file_name} does not parse: fix the text before the form writes into it") from None


def section_of(document: dict[str, Any], path: Sequence[str]) -> dict[Any, Any] | None:
    """The mapping that holds the setting at `path`, or None when a key above it is missing or holds no section."""
    node: Any = document

    for key in path[:-1]:
        node = node.get(key) if isinstance(node, dict) else None

    return node if isinstance(node, dict) else None


def value_node(text: str, path: Sequence[str]) -> yaml.Node | None:
    """The YAML node of the value at `path`, found with yaml.compose, which runs nothing; None when a key is missing."""
    node: yaml.Node | None = yaml.compose(text)

    for key in path:
        child = child_node(node, key)
        node = child[1] if child else None

    return node


def value_span(text: str, node: yaml.Node) -> tuple[int, int]:
    """
    Where `node` is written in `text`, from its first character to its last: a block list ends at its last item and a
    block text at its last character, never at the comments and blank lines before the next key. An empty value is the
    place right after its key.
    """
    last = node

    while isinstance(last, yaml.CollectionNode) and not last.flow_style and last.value:
        last = last.value[-1][1] if isinstance(last, yaml.MappingNode) else last.value[-1]

    start = node.start_mark.index
    return start, max(start, len(text[: last.end_mark.index].rstrip()))


def yaml_value(value: SettingValue) -> str:
    """
    One value as flow YAML, never folded, written by the library that reads it back, so a text it would read as another
    kind, such as `yes` or `12`, is quoted.
    """
    written = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True, width=sys.maxsize)
    return written.removesuffix("\n...\n").removesuffix("\n")


def kind_of(value: object) -> str:
    """A value's kind as JSON names it, so a whole number and a decimal are both a number and the form may write either."""
    match value:
        case bool():
            return "boolean"
        case int() | float():
            return "number"
        case str():
            return "string"
        case list():
            return "list"
        case _:
            return type(value).__name__


class InvalidSettingsError(RuntimeError):
    """
    The app would not start with the settings: config/ or .env hold a value the settings refuse, a setup the startup
    checks refuse, or a startup on them failed. The CLI or the Web API does not start, and a reload or a Web save keeps
    the running settings. Each problem is located and carries the message, never the value: pydantic's own text shows
    the input, which can be a secret from .env, so neither the message nor a traceback carries the ValidationError.
    """

    def __init__(self, problems: list[SettingsProblem]) -> None:
        self.problems = problems
        super().__init__(
            "\n".join(["The app would not start with the settings in config/ and .env:", *(f"  - {problem}" for problem in problems)])
        )


class TradingSetupError(RuntimeError):
    """
    The trading settings or the broker login do not let the CLI or the Web API start. The message says what to change;
    `path` is the setting it is about, when a settings file sets it.
    """

    def __init__(self, message: str, path: str | None = None) -> None:
        self.path = path
        super().__init__(message)


def startup_settings(
    project_root: Path,
    candidates: Mapping[SettingsFile, str] | None = None,
    environment: SystemEnvironment | None = None,
    audience: Audience | None = None,
) -> AppConfig:
    """
    The settings a start, a reload or a Web save opens the app on, through every check startup runs before it opens
    anything: the load (each file parsed, every key the app would not read refused, every value validated), the trading
    setup, the environment and the audience the process started in (`environment` and `audience`, None at its first
    start), the accounts key, the AI's web and X search on an audience without news articles, and every offered AI
    provider's model id and key. Raises one InvalidSettingsError with every refusal located once, never a value.
    """
    texts = settings_texts(project_root, candidates)
    config = load_settings(project_root, texts)

    try:
        validate_trading_environment(config)
        validate_started_setup_unchanged(config, environment or config.environment, audience or config.audience)
        validate_accounts_environment(config)
    except (TradingSetupError, AccountsSetupError) as error:
        raise InvalidSettingsError([locate(texts, error.path, str(error))]) from None

    searches = {
        "behavior.enable_web_search": config.behavior.enable_web_search,
        "behavior.enable_x_search": config.behavior.enable_x_search,
    }

    if not config.audience.news_articles and (searching := [path for path, enabled in searches.items() if enabled]):
        message = f"must be false on audience {config.audience.value}: a search brings news sites' and X's text, which it may not use"
        raise InvalidSettingsError([locate(texts, path, message) for path in searching])

    if missing := config.ai.missing_keys():
        raise InvalidSettingsError([locate(texts, path, f"{need}; the app would not start") for path, need in missing.items()])

    return config


def validate_trading_environment(config: AppConfig) -> None:
    """
    Refuses a setup that could send an order nobody meant to send, or use a credential the environment must not see,
    before any broker or database is contacted. What each environment allows is SystemEnvironment's table, and what
    each audience allows is Audience's:

    - the brokers the environment and the audience allow (dev: the mock only; public: the mock only);
    - the order modes the environment allows (only prod: order mode live);
    - mock_only order mode needs the mock broker, live needs Shioaji;
    - dev and test refuse to start while a production Shioaji credential is set;
    - prod refuses SQLite;
    - Shioaji needs the credentials its environment reads.
    Order mode disabled never orders, so in test and prod it may read a Shioaji account.
    """
    environment, provider, mode = config.environment, config.trading.execution_provider, config.trading.order_mode
    validate_brokers(config)

    if mode not in environment.order_modes:
        allowed = " or ".join(other.value for other in SystemEnvironment if mode in other.order_modes)
        raise TradingSetupError(f"order_mode {mode.value} needs environment {allowed}, not {environment.value}", "trading.order_mode")

    if mode == OrderMode.MOCK_ONLY and provider != ExecutionProvider.MOCK:
        raise TradingSetupError(
            f"order_mode mock_only needs execution_provider mock, not {provider.value}. "
            f"Use order_mode disabled to read the {provider.value} account without ordering",
            "trading.order_mode",
        )

    if mode == OrderMode.LIVE and provider != ExecutionProvider.SHIOAJI:
        raise TradingSetupError(f"order_mode live needs execution_provider shioaji, not {provider.value}", "trading.order_mode")

    if config.db.backend not in environment.databases:
        allowed = " or ".join(sorted(backend.value for backend in environment.databases))
        raise TradingSetupError(
            f"environment {environment.value} needs db.backend {allowed}, not {config.db.backend.value}", "db.backend"
        )

    validate_environment_credentials(config)


def validate_brokers(config: AppConfig) -> None:
    """The broker must be one the environment allows and one the audience allows: a public site never reaches a real account."""
    environment, audience, provider = config.environment, config.audience, config.trading.execution_provider

    if provider not in environment.brokers:
        allowed = ", ".join(sorted(broker.value for broker in environment.brokers))
        raise TradingSetupError(
            f"environment {environment.value} trades only on {allowed}, not {provider.value}", "trading.execution_provider"
        )

    if provider not in audience.brokers:
        allowed = ", ".join(sorted(broker.value for broker in audience.brokers))
        raise TradingSetupError(
            f"audience {audience.value} trades only on {allowed}, not {provider.value}: nobody trades in a visitor's account",
            "trading.execution_provider",
        )


def validate_environment_credentials(config: AppConfig) -> None:
    """The Shioaji variables the environment must not see, and those its broker needs. Names only, never a value."""
    environment, given = config.environment, config.shioaji.given()

    if refused := [credential.value for credential in environment.refused_credentials if credential in given]:
        raise TradingSetupError(
            f"environment {environment.value} refuses to start while {', '.join(refused)} is set: the production Shioaji "
            "credentials belong only in the production machine's environment or .env",
            "environment",
        )

    needed = environment.shioaji_credentials if config.trading.execution_provider == ExecutionProvider.SHIOAJI else ()

    if missing := [credential.value for credential in needed if credential not in given]:
        raise TradingSetupError(
            f"execution_provider shioaji in environment {environment.value} needs {', '.join(missing)} in the environment or .env"
        )


def validate_started_setup_unchanged(config: AppConfig, environment: SystemEnvironment, audience: Audience) -> None:
    """
    A process keeps the environment and the audience it started in: the environment decides which credentials it reads,
    and the audience which sources it may reach and whom it may show them, so a public site never starts asking Yahoo or
    TWSE MIS because a save said so. A settings change on disk or from the Web that changes either is refused, and the
    running settings keep serving.
    """
    if config.environment != environment:
        raise TradingSetupError(
            f"environment is {config.environment.value} in the settings, but this process started as {environment.value}: "
            "the environment changes only when the app restarts",
            "environment",
        )

    if config.audience != audience:
        raise TradingSetupError(
            f"audience is {config.audience.value} in the settings, but this process started as {audience.value}: "
            "the audience changes only when the app restarts",
            "audience",
        )


def validate_editor_reachable(config: AppConfig, texts: Mapping[SettingsFile, str], host: str) -> None:
    """
    A Web save must leave the administrator who makes it a way back into the editor: the host they reached it at stays
    in api.allowed_hosts, and every settings file stays within api.settings_file_max_bytes. InvalidSettingsError at the
    setting that would lock them out.
    """
    too_large = [file.file_name for file, text in texts.items() if len(text.encode("utf-8")) > config.api.settings_file_max_bytes]
    problems = []

    if host not in config.api.allowed_hosts:
        problems.append(locate(texts, "api.allowed_hosts", f"leaves out {host}, the host this editor is reached at"))

    if too_large:
        message = f"is smaller than {', '.join(too_large)}: the editor could no longer read it"
        problems.append(locate(texts, "api.settings_file_max_bytes", message))

    if problems:
        raise InvalidSettingsError(problems)


class AccountsSetupError(RuntimeError):
    """
    The user accounts cannot start: the accounts key is not 32 base64url bytes, or the environment needs ACCOUNTS_KEY
    and it is not set. The message names where the key came from; `path` is the setting it is about, if any.
    """

    def __init__(self, message: str, path: str | None = None) -> None:
        self.path = path
        super().__init__(message)


def accounts_key_bytes(key: SecretStr) -> bytes:
    """The accounts key's bytes: base64url, its padding optional, as the app writes secrets/accounts.key. Raises ValueError."""
    return urlsafe_b64decode(key.get_secret_value() + "=" * (-len(key.get_secret_value()) % 4))


def validate_accounts_key(key: SecretStr, source: str) -> SecretStr:
    """`key`, or AccountsSetupError naming `source` when it is not 32 random bytes in base64url."""
    try:
        length = len(accounts_key_bytes(key))
    except ValueError:
        length = 0

    if length != 32:
        raise AccountsSetupError(f"{source} must be 32 random bytes in base64url, as the app writes secrets/accounts.key.")

    return key


def validate_accounts_environment(config: AppConfig) -> SecretStr | None:
    """
    ACCOUNTS_KEY when the environment or .env sets it, or None when it is unset or blank: the key file is used then,
    where the environment allows one (SystemEnvironment.accounts_key_file). Prod refuses to start without the variable.
    """
    environment = config.environment

    if config.accounts.key is None and not environment.accounts_key_file:
        raise AccountsSetupError(
            f"environment {environment.value} needs ACCOUNTS_KEY in the environment or .env: it never creates "
            "secrets/accounts.key, because its app folder may not survive a redeploy and a new key locks every account",
            "environment",
        )

    return None if config.accounts.key is None else validate_accounts_key(config.accounts.key, "ACCOUNTS_KEY")
