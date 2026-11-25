"""List every settings field that has a Python default and also a value in config/appsetting.yaml.

Run from backend/:

    uv run python tools/settings_defaults.py [--yaml <a deployment's appsetting.yaml>]

Every value lives in one place: a setting the file shows is required and has no code default, and a setting with a
code default is not in the shipped file. The script walks AppConfig's fields and the settings models they hold, and
prints one line per field that has both: its dotted path, the code default and the YAML value, which is parsed with
the field's type first. A settings model that the YAML sets is walked, not listed. A field whose class names what the
site goes without while a file does not set it (`without` in its json_schema_extra) has no default to copy: its empty
code value means unset, so it is not listed. It exits 1 when any field has both and 0 when none does. On a
deployment's file a line is a value that file sets over the code's default.
"""

import argparse
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, TypeAdapter

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "src"))

from b_application.config.app_config import AppConfig  # noqa: E402


@dataclass(frozen=True)
class DuplicatedSetting:
    path: str
    default: Any
    shipped: Any

    def __str__(self) -> str:
        return f"{self.path}  code={self.default!r}  yaml={self.shipped!r}"


def settings_model(annotation: Any) -> type[BaseModel] | None:
    return annotation if isinstance(annotation, type) and issubclass(annotation, BaseModel) else None


def duplicated_settings(model: type[BaseModel], values: Mapping[str, Any], prefix: str = "") -> Iterator[DuplicatedSetting]:
    for name, field in model.model_fields.items():
        if name not in values:
            continue
        nested = settings_model(field.annotation)
        if nested is not None:
            yield from duplicated_settings(nested, values[name] or {}, f"{prefix}{name}.")
            continue
        if field.is_required() or (isinstance(field.json_schema_extra, dict) and "without" in field.json_schema_extra):
            continue
        shipped = TypeAdapter(field.annotation).validate_python(values[name])
        yield DuplicatedSetting(f"{prefix}{name}", field.get_default(call_default_factory=True), shipped)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List settings fields that have a Python default and a YAML value.")
    parser.add_argument("--yaml", type=Path, default=BACKEND.parent / "config" / "appsetting.yaml", help="the settings file")
    arguments = parser.parse_args(argv)
    values = yaml.safe_load(arguments.yaml.read_text(encoding="utf-8")) or {}
    duplicates = list(duplicated_settings(AppConfig, values))
    for duplicate in duplicates:
        print(duplicate)
    print(f"\n{len(duplicates)} fields have both a Python default and a YAML value.")
    return 1 if duplicates else 0


if __name__ == "__main__":
    sys.exit(main())
