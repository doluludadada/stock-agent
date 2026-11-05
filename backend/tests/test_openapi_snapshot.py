from export_openapi import OUTPUTS, SNAPSHOT, outputs_text, snapshot_text


def test_the_frontend_contract_matches_the_api() -> None:
    """The frontend types and catalog come from these files. Regenerate them with `uv run python tools/export_openapi.py`."""
    assert SNAPSHOT.read_text(encoding="utf-8") == snapshot_text()
    assert OUTPUTS.read_text(encoding="utf-8") == outputs_text()
