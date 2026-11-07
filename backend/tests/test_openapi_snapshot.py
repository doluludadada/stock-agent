from export_openapi import FIELDS, OUTPUTS, SNAPSHOT, fields_text, outputs_text, snapshot_text


def test_the_frontend_contract_matches_the_api() -> None:
    """
    The frontend types, catalog and settings fields come from these files. Regenerate them with
    `PYTHONPATH=src uv run python tools/export_openapi.py`.
    """
    assert SNAPSHOT.read_text(encoding="utf-8") == snapshot_text()
    assert OUTPUTS.read_text(encoding="utf-8") == outputs_text()
    assert FIELDS.read_text(encoding="utf-8") == fields_text()
