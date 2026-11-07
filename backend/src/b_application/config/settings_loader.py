"""
How the CLI and the Web API load their settings at startup, and refuse an unsafe trading setup. The administrator's
settings form takes its fields from the same settings classes, writes each change into the files' text in place here,
and checks the new texts through the same functions, so a saved file is one the app starts with.
"""

import hashlib
import json
import sys
from base64 import urlsafe_b64decode
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import date
from functools import cache
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin, override

import yaml
from pydantic import BaseModel, JsonValue, SecretStr, TypeAdapter, ValidationError
from pydantic.json_schema import GenerateJsonSchema
from pydantic_core import ErrorDetails, core_schema, to_jsonable_python

from a_domain.ports.system.settings_files import SettingChange, SettingField, SettingsEdit, SettingsProblem
from a_domain.types.enums import Audience, InstructionKey, SettingKind, SettingsFile, SystemEnvironment
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
        raise InvalidSettingsError([validation_problem(texts, problem) for problem in error.errors()]) from None


def validation_problem(texts: Mapping[SettingsFile, str], error: ErrorDetails) -> SettingsProblem:
    """
    One of pydantic's refusals, located, with its type as the code and the schema's limits it names as the params. Only
    those limits: the rest of pydantic's context can carry the input, which can be a secret from .env.
    """
    limits = ("gt", "ge", "lt", "le", "multiple_of", "expected", "min_length", "max_length", "pattern")
    params = {key: value for key, value in error.get("ctx", {}).items() if key in limits and isinstance(value, str | int | float)}
    problem = locate(texts, ".".join(str(part) for part in error["loc"]), error["msg"])
    return replace(problem, code=error["type"], params=params)


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

    file, keys = setting_place(path)
    return locate_in(texts, file, keys, path, message)


def setting_place(path: str) -> tuple[SettingsFile, list[str]]:
    """
    The file that sets a setting and its keys there: a prompt, or a path below one, in instructions.yaml at its key;
    anything else in appsetting.yaml along its dotted path.
    """
    prompt = next((key for key in InstructionKey if path == key.settings_path or path.startswith(f"{key.settings_path}.")), None)

    if prompt is not None:
        return SettingsFile.INSTRUCTIONS, [prompt.value]

    return SettingsFile.APPSETTING, path.split(".")


def locate_in(texts: Mapping[SettingsFile, str], file: SettingsFile, keys: Sequence[str], path: str, message: str) -> SettingsProblem:
    """The problem at the start of the deepest of `keys` the file's YAML has."""
    try:
        found = key_value_nodes(yaml.compose(texts[file]), keys)
    except yaml.YAMLError:
        found = []

    if not found:
        return SettingsProblem(message=message, path=path)

    mark = found[-1][0].start_mark
    return SettingsProblem(message=message, file=file, path=path, line=mark.line + 1, column=mark.column + 1)


def key_value_nodes(root: yaml.Node | None, keys: Sequence[str]) -> list[tuple[yaml.Node, yaml.Node]]:
    """
    The (key, value) nodes of each of `keys` under `root`, a node yaml.compose read, which runs nothing: from the top,
    up to the first key it lacks.
    """
    found: list[tuple[yaml.Node, yaml.Node]] = []
    node = root

    for key in keys:
        if (child := child_node(node, key)) is None:
            break

        found.append(child)
        node = child[1]

    return found


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


def settings_fields(documents: Mapping[SettingsFile, Mapping[str, Any]]) -> list[SettingField]:
    """
    The administrator's settings form: every setting of appsetting.yaml and every AI prompt of instructions.yaml, in
    the order of the settings classes, depth first, each with the value `documents` (the files as parsed_document reads
    them) set, else its default. The fields come from settings_schema(), so a setting a class adds appears without a
    list kept by hand, and no setting the environment owns or the loader sets is one. A section is followed into its
    settings; a section with none (line) gives no field.
    """
    schema = settings_schema()
    return list(section_fields(schema, schema, "", documents))


def section_fields(
    schema: Mapping[str, Any], section: Mapping[str, Any], prefix: str, documents: Mapping[SettingsFile, Mapping[str, Any]]
) -> Iterator[SettingField]:
    for name, node in section.get("properties", {}).items():
        path = f"{prefix}{name}"
        value = setting_value(documents, path, node)
        resolved = schema_node(schema, node, value)

        if "properties" in resolved:
            yield from section_fields(schema, resolved, f"{path}.", documents)
            continue

        options = resolved.get("enum") or schema_node(schema, resolved.get("items", {}), None).get("enum", ())
        yield SettingField(
            path=path,
            kind=setting_kind(schema, resolved, value),
            value=value,
            options=tuple(str(option) for option in options),
            minimum=resolved.get("minimum"),
            maximum=resolved.get("maximum"),
            exclusive_minimum=resolved.get("exclusiveMinimum"),
            exclusive_maximum=resolved.get("exclusiveMaximum"),
            restart_only=resolved.get("restart_only", False),
        )


def setting_value(documents: Mapping[SettingsFile, Mapping[str, Any]], path: str, node: Mapping[str, Any]) -> JsonValue:
    """
    The value the file sets at `path` as JSON, so a YAML date is its ISO text and a number key a text; else the
    schema's default, else None.
    """
    file, keys = setting_place(path)
    value: Any = documents.get(file, {})

    for key in keys:
        if not isinstance(value, Mapping) or key not in value:
            return node.get("default")

        value = value[key]

    return to_jsonable_python(value)


def schema_node(schema: Mapping[str, Any], node: Mapping[str, Any], value: object) -> dict[str, Any]:
    """
    The schema a setting's value is read by: its $ref followed, the setting's own keys over the definition's, and of
    several kinds (anyOf) the one that is not null, else the first whose JSON type the value has, else the first.
    """
    resolved = dict(node)

    while "$ref" in resolved:
        reference = resolved.pop("$ref")
        resolved = {**schema["$defs"][reference.rsplit("/", 1)[1]], **resolved}

    if "anyOf" not in resolved:
        return resolved

    branches = [schema_node(schema, branch, value) for branch in resolved.pop("anyOf") if branch.get("type") != "null"]
    chosen = branches[0] if len(branches) == 1 else next((branch for branch in branches if has_json_type(value, branch)), branches[0])
    return {**chosen, **resolved}


def has_json_type(value: object, node: Mapping[str, Any]) -> bool:
    """The value is of the node's JSON type; a whole number is a number, and an integer too."""
    kind = kind_of(value)
    return node.get("type") == kind or (node.get("type") == "integer" and kind == "number" and isinstance(value, int))


def setting_kind(schema: Mapping[str, Any], node: Mapping[str, Any], value: JsonValue) -> SettingKind:
    """How the form shows a setting `node` reads: an enum is a CHOICE, and a map a STRUCTURE."""
    if "enum" in node:
        return SettingKind.CHOICE

    match node.get("type"):
        case "array":
            return list_kind(schema_node(schema, node.get("items", {}), None), value)
        case "boolean":
            return SettingKind.SWITCH
        case "integer":
            return SettingKind.INTEGER
        case "number":
            return SettingKind.NUMBER
        case "string":
            return SettingKind.TEXT
        case _:
            return SettingKind.STRUCTURE


def list_kind(items: Mapping[str, Any], value: JsonValue) -> SettingKind:
    """
    A list's: CHOICES of an enum's members; LINES of scalars, or of the texts or numbers the file writes where the
    settings read objects (technical.built_in_strategies names strategy ids the loader reads into strategies); any
    other list is a STRUCTURE.
    """
    if "enum" in items:
        return SettingKind.CHOICES

    if items.get("type") in ("string", "integer", "number", "boolean"):
        return SettingKind.LINES

    written_as_scalars = isinstance(value, list) and bool(value) and all(isinstance(item, str | int | float) for item in value)
    return SettingKind.LINES if written_as_scalars else SettingKind.STRUCTURE


def with_changes(texts: Mapping[SettingsFile, str], changes: Sequence[SettingChange]) -> list[SettingsEdit]:
    """
    The settings form's changes written into `texts`, the text of every settings file: the edit of each file they
    change, with the settings it changes. A change to the value its field shows changes nothing. SettingsEditError,
    naming the setting but never a value, for a path that is no field of the form, or a change with_change cannot write.
    """
    documents = {file: editable_document(file, text) for file, text in texts.items()}
    shown = {field.path: field.value for field in settings_fields(documents)}
    edited, changed = dict(texts), {file: dict[str, None]() for file in texts}

    for change in changes:
        if change.path not in shown:
            raise SettingsEditError(f"{change.path} is no setting of the settings form")

        if shown[change.path] == change.value:
            continue

        file, keys = setting_place(change.path)
        edited[file] = with_change(file, edited[file], keys, change.value)
        shown[change.path], changed[file][change.path] = change.value, None

    return [
        SettingsEdit(
            file=file,
            base_revision=settings_revision(texts[file]),
            text=edited[file],
            revision=settings_revision(edited[file]),
            changed=tuple(changed[file]),
        )
        for file in texts
        if edited[file] != texts[file]
    ]


def with_change(file: SettingsFile, text: str, keys: Sequence[str], value: JsonValue) -> str:
    """
    `text` with `value` written at `keys` as YAML the loader reads back as that value: over the value there in place,
    or inserted where edited_texts says; every other character stays, comments and layout included. SettingsEditError
    for a text that does not parse, a value of another kind than the one the file sets, a setting below a flow mapping
    or a value that is no mapping, or a value no way of writing reads back as.
    """
    path, document = ".".join(keys), editable_document(file, text)
    section = section_of(document, keys)
    current = section.get(keys[-1]) if section is not None else None
    known = to_jsonable_python(current)

    if None not in (known, value) and kind_of(known) != kind_of(value):
        raise SettingsEditError(f"{path} holds a value of kind {kind_of(known)} in {file.file_name}, not {kind_of(value)}")

    written = in_file_kinds(value, current)
    candidates = edited_texts(text, keys, written)
    expected = with_value(document, keys, written) if candidates else None
    edited = next((candidate for candidate in candidates if reads_back(file, candidate, expected)), None)

    if edited is None:
        raise SettingsEditError(f"{path} cannot be written in place in {file.file_name}; change it in the file")

    return edited


def editable_document(file: SettingsFile, text: str) -> dict[str, Any]:
    try:
        return parsed_document(file, text)
    except InvalidSettingsError:
        raise SettingsEditError(f"{file.file_name} does not parse: fix it in the file before the form writes into it") from None


def section_of(document: dict[str, Any], path: Sequence[str]) -> dict[Any, Any] | None:
    """The mapping that holds the setting at `path`, or None when a key above it is missing or holds no section."""
    node: Any = document

    for key in path[:-1]:
        node = node.get(key) if isinstance(node, dict) else None

    return node if isinstance(node, dict) else None


def with_value(document: dict[str, Any], keys: Sequence[str], value: Any) -> dict[str, Any]:
    """`document`, changed in place, with `value` at `keys`, and any section it lacks on the way added."""
    node = document

    for key in keys[:-1]:
        node = node.setdefault(key, {})

    node[keys[-1]] = value
    return document


def reads_back(file: SettingsFile, text: str, expected: dict[str, Any] | None) -> bool:
    try:
        return parsed_document(file, text) == expected
    except InvalidSettingsError:
        return False


def in_file_kinds(value: JsonValue, current: Any) -> Any:
    """
    `value` in the YAML kinds the file writes `current` in, so a change keeps the file's way of writing it: a text for a
    date as that date, and the keys of a map whose keys are all whole numbers, such as market.stock_ticks, as numbers.
    """
    match current, value:
        case date(), str():
            try:
                return date.fromisoformat(value)
            except ValueError:
                return value
        case dict(), dict() if current and all(isinstance(key, int) for key in current):
            return {int(key) if key.isdecimal() else key: item for key, item in value.items()}
        case _:
            return value


def edited_texts(text: str, keys: Sequence[str], value: Any) -> list[str]:
    """
    `text` with `value` written at `keys`, once for each way writings() offers: in place of the value the text has
    there, right after its key's colon, or at the value's own place when a comment comes between them; or, for a setting
    the text does not set, inserted after the last setting of the deepest block mapping on the way, at the column of
    that mapping's keys, with any section it lacks as a nested block mapping. None for a setting below a flow mapping or
    below a key whose value is no mapping.
    """
    root = yaml.compose(text)
    found = key_value_nodes(root, keys)

    if len(found) == len(keys):
        key, node = found[-1]
        start, end = value_span(text, node)
        colon = text.index(":", key.end_mark.index) + 1
        begin = colon if not text[colon:start].strip() else start
        written = writings(value, node, key.start_mark.column)
        return [f"{text[:begin]}{writing if begin == colon else writing.lstrip()}{text[end:]}" for writing in written]

    if (place := insertion_place(text, found[-1][1] if found else root)) is None:
        return []

    position, column = place
    missing = keys[len(found) :]
    head = text[:position] + ("\n" if text[:position] and not text[:position].endswith("\n") else "")
    keys_text = "\n".join(f"{' ' * (column + 2 * depth)}{key}:" for depth, key in enumerate(missing))
    return [f"{head}{keys_text}{writing}{text[position:]}" for writing in writings(value, None, column + 2 * (len(missing) - 1))]


def insertion_place(text: str, parent: yaml.Node | None) -> tuple[int, int] | None:
    """
    Where a setting the file lacks goes under `parent`: the end of the line of its last setting, at the column of its
    keys; the end of a document that holds no setting yet, at column 0; None under a flow mapping or no mapping.
    """
    if parent is None:
        return len(text), 0

    if not isinstance(parent, yaml.MappingNode) or parent.flow_style or not parent.value:
        return None

    end = value_span(text, parent)[1]
    newline = text.find("\n", end)
    return (newline if newline >= 0 else len(text)), parent.value[0][0].start_mark.column


def writings(value: Any, node: yaml.Node | None, column: int) -> list[str]:
    """
    Each way to write `value` after the colon of a key at `column`, over `node`, the value there (None for a new key),
    the preferred first: a text of several lines as a literal block; a map or a list in block style on the lines below,
    at the column of the block collection with items it replaces; anything else, an empty list or map included, in
    flow style on the key's line; and a text double-quoted, which reads back as whatever it holds, wherever it stands.
    """
    if isinstance(value, str):
        quoted = f" {yaml_value(value, '"')}"
        return [f" {block_value(value, column)}", quoted] if "\n" in value else [f" {yaml_value(value)}", quoted]

    if isinstance(value, list | dict) and value and isinstance(node, yaml.CollectionNode) and not node.flow_style and node.value:
        indent = node.start_mark.column
        return [f"\n{' ' * indent}{block_value(value, indent)}", f" {yaml_value(value)}"]

    return [f" {yaml_value(value)}"]


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


def yaml_value(value: Any, style: str | None = None) -> str:
    """
    One value in flow style, never folded, written by the library that reads it back, so a text it would read as
    another kind, such as `yes` or `12`, is quoted; style '"' double-quotes a text, its line breaks escaped.
    """
    return dumped(
        yaml.safe_dump(value, default_flow_style=True, default_style=style, allow_unicode=True, width=sys.maxsize, sort_keys=False)
    )


def block_value(value: Any, column: int) -> str:
    """
    `value` in block style: a text as a literal block, its lines two columns past its key's `column`; a map or a list
    with each line after the first at `column`, the column of the value it replaces.
    """
    written = yaml.safe_dump(
        value,
        default_flow_style=False,
        default_style="|" if isinstance(value, str) else None,
        allow_unicode=True,
        width=sys.maxsize,
        sort_keys=False,
    )
    first, *rest = dumped(written).split("\n")
    return "\n".join([first, *(f"{' ' * column}{line}" if line else line for line in rest)])


def dumped(written: str) -> str:
    """What yaml.safe_dump wrote, without the line end it closes the value with, and without its document end marker."""
    return (written[: -len("...\n")] if written.endswith("\n...\n") else written).removesuffix("\n")


def kind_of(value: object) -> str:
    """A value's JSON type, except that a whole number and a decimal are both a number, so the form may write either."""
    match value:
        case bool():
            return "boolean"
        case int() | float():
            return "number"
        case str():
            return "string"
        case list():
            return "array"
        case dict():
            return "object"
        case None:
            return "null"
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

    validate_ai_setup(config, texts)
    return config


def validate_ai_setup(config: AppConfig, texts: Mapping[SettingsFile, str]) -> None:
    """
    The AI's web and X search, which an audience without news articles refuses (search_on_open_data), and every offered
    provider's model id and key: InvalidSettingsError at each setting that refuses.
    """
    searches = {
        "behavior.enable_web_search": config.behavior.enable_web_search,
        "behavior.enable_x_search": config.behavior.enable_x_search,
    }

    if not config.audience.news_articles and (searching := [path for path, enabled in searches.items() if enabled]):
        message = f"must be false on audience {config.audience.value}: a search brings news sites' and X's text, which it may not use"
        params = {"audience": config.audience.value}
        raise InvalidSettingsError(
            [replace(locate(texts, path, message), code="search_on_open_data", params=params) for path in searching]
        )

    if missing := config.ai.missing_keys():
        raise InvalidSettingsError(
            [
                replace(locate(texts, path, f"{need.message}; the app would not start"), code=need.code, params=need.params)
                for path, need in missing.items()
            ]
        )


def validate_trading_environment(config: AppConfig) -> None:
    """
    Refuses a setup that could reach data or a credential the environment must not see, before any broker or database
    is contacted. What each environment allows is SystemEnvironment's table:

    - dev and test refuse to start while a production Shioaji credential is set;
    - prod refuses SQLite.
    Which broker a run orders on is the run's own choice, and the order gates check at each order that a real broker's
    login is on the server the environment trades on.
    """
    environment = config.environment

    if config.db.backend not in environment.databases:
        allowed = " or ".join(sorted(backend.value for backend in environment.databases))
        raise TradingSetupError(
            f"environment {environment.value} needs db.backend {allowed}, not {config.db.backend.value}", "db.backend"
        )

    if refused := [credential.value for credential in environment.refused_credentials if credential in config.shioaji.given()]:
        raise TradingSetupError(
            f"environment {environment.value} refuses to start while {', '.join(refused)} is set: the production Shioaji "
            "credentials belong only in the production machine's environment or .env",
            "environment",
        )


def validate_started_setup_unchanged(config: AppConfig, environment: SystemEnvironment, audience: Audience) -> None:
    """
    A process keeps the environment and the audience it started in: the environment decides which credentials it reads,
    and the audience which sources it may reach and whom it may show them, so a public site never starts asking a news site or
    Shioaji because a save said so. A settings change on disk or from the Web that changes either is refused, and the
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
