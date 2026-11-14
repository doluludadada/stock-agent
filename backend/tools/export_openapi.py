"""
Writes the Web API's OpenAPI document to frontend/src/shared/api/openapi.json, the contract the frontend generates
its types from (`bun run api:types`); the outputs of each indicator kind to indicator-outputs.json, which the formula
designer's catalog reads; and the settings form's fields, each with its control, group, options and unit, to
settings-fields.json, which the frontend's i18n test reads to require a label and a help for each field and a label for
each option, group and unit.
tests/test_openapi_snapshot.py fails while any of them is out of date.

    cd backend && PYTHONPATH=src uv run python tools/export_openapi.py
"""

import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from a_domain.types.enums import IndicatorKind
from b_application.config.settings_loader import settings_fields
from d_presentation.web.app import create_app

FOLDER = Path(__file__).resolve().parents[2] / "frontend" / "src" / "shared" / "api"
SNAPSHOT = FOLDER / "openapi.json"
OUTPUTS = FOLDER / "indicator-outputs.json"
FIELDS = FOLDER / "settings-fields.json"


def openapi_document() -> dict[str, Any]:
    """The document the running app serves at /openapi.json; building it opens no runtime."""
    return create_app(lambda: nullcontext()).openapi()


def snapshot_text() -> str:
    return json.dumps(openapi_document(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def outputs_text() -> str:
    return json.dumps({kind.value: [output.value for output in kind.outputs] for kind in IndicatorKind}, indent=2) + "\n"


def fields_text() -> str:
    """The form's fields in form order, from the settings classes alone: no settings file's value."""
    fields = [
        {"path": field.path, "kind": field.kind, "group": field.group, "options": list(field.options), "unit": field.unit}
        for field in settings_fields({})
    ]
    return json.dumps(fields, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    SNAPSHOT.write_text(snapshot_text(), encoding="utf-8")
    OUTPUTS.write_text(outputs_text(), encoding="utf-8")
    FIELDS.write_text(fields_text(), encoding="utf-8")
    print(f"Wrote {SNAPSHOT}, {OUTPUTS} and {FIELDS}")
