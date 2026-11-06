"""The settings form's endpoint over HTTP, on a temporary copy of config/: it writes a setting into a text, never a file."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from support.harness import MEMBER, MEMBER_PASSWORD, build_harness
from support.web import serve

pytestmark = pytest.mark.asyncio

REPOSITORY_CONFIG = Path(__file__).resolve().parents[2] / "config"
APPSETTING = "/v1/admin/settings/appsetting"
FORM = f"{APPSETTING}/form"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of config/, with the active AI provider's key and a placeholder ACCOUNTS_KEY, so the check runs anywhere."""
    shutil.copytree(REPOSITORY_CONFIG, tmp_path / "config")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ACCOUNTS_KEY", "A" * 43)
    return tmp_path


def on_disk(project: Path) -> str:
    return (project / "config" / "appsetting.yaml").read_text(encoding="utf-8")


def change(path: str, value: Any) -> dict[str, Any]:
    return {"path": path.split("."), "value": value}


def schema_at(schema: dict[str, Any], path: str) -> dict[str, Any]:
    """The schema of one setting, following each section's $ref the way the page does."""
    node = schema
    for key in path.split("."):
        node = node["properties"][key]
        while "$ref" in node:
            node = {**schema["$defs"][node["$ref"].rsplit("/", 1)[1]], **{k: v for k, v in node.items() if k != "$ref"}}
    return node


async def test_a_change_is_written_in_place_and_every_other_line_comment_and_key_stays_as_it_was(project: Path) -> None:
    original = on_disk(project)

    async with serve(build_harness(settings_root=project)) as client:
        revision = (await client.get(APPSETTING)).json()["status"]["revision"]
        answer = await client.post(FORM, json={"text": original, "changes": [change("ai.temperature", 0.4)]})
        form = answer.json()
        preview = (await client.post(f"{APPSETTING}/preview", json={"revision": revision, "text": form["text"]})).json()

    assert answer.status_code == 200 and "temperature: 0.7\n" in original
    assert form["text"] == original.replace("temperature: 0.7\n", "temperature: 0.4\n", 1)
    assert form["values"]["ai.temperature"] == 0.4 and form["values"]["trading.order_mode"] == "mock_only"
    assert (preview["changed"], preview["problems"]) == (["ai.temperature"], [])
    assert on_disk(project) == original


async def test_switches_choices_and_lists_are_written_as_the_loader_reads_them_back(project: Path) -> None:
    original = on_disk(project)
    changes = [
        change("accounts.registration_open", False),
        change("trading.order_mode", "disabled"),
        change("ai.user_selectable", ["gemini"]),
    ]

    async with serve(build_harness(settings_root=project)) as client:
        form = (await client.post(FORM, json={"text": original, "changes": changes})).json()

    expected = (
        original.replace("registration_open: true\n", "registration_open: false\n", 1)
        .replace("order_mode: mock_only\n", "order_mode: disabled\n", 1)
        .replace("user_selectable: []\n", "user_selectable: [gemini]\n", 1)
    )
    assert form["text"] == expected
    values = form["values"]
    assert (values["accounts.registration_open"], values["trading.order_mode"], values["ai.user_selectable"]) == (
        False,
        "disabled",
        ["gemini"],
    )


async def test_a_value_the_app_would_refuse_is_written_and_the_check_says_why_at_its_line(project: Path) -> None:
    original = on_disk(project)

    async with serve(build_harness(settings_root=project)) as client:
        revision = (await client.get(APPSETTING)).json()["status"]["revision"]
        form = (await client.post(FORM, json={"text": original, "changes": [change("ai.temperature", 5)]})).json()
        preview = (await client.post(f"{APPSETTING}/preview", json={"revision": revision, "text": form["text"]})).json()

    [problem] = preview["problems"]
    assert "temperature: 5\n" in form["text"] and form["values"]["ai.temperature"] == 5
    assert (problem["file"], problem["path"], problem["line"]) == (
        "appsetting",
        "ai.temperature",
        form["text"].count("\n", 0, form["text"].index("temperature: 5")) + 1,
    )


@pytest.mark.parametrize(
    ("text", "changes", "named"),
    [
        (None, [change("ai.temperatur", 0.4)], "ai.temperatur"),
        (None, [change("ai", 0.4)], "ai"),
        (None, [change("ai.temperature.limit", 1)], "ai.temperature.limit"),
        (None, [change("ai.temperature", True)], "ai.temperature"),
        (None, [change("accounts.registration_open", "sometimes")], "accounts.registration_open"),
        ("trading:\n  order_mode: [mock_only\n", [change("trading.order_mode", "disabled")], "appsetting.yaml"),
    ],
    ids=["unknown-key", "section", "below-a-setting", "boolean-for-number", "string-for-boolean", "does-not-parse"],
)
async def test_a_change_the_text_cannot_take_is_refused_naming_the_setting_and_nothing_is_written(
    project: Path, text: str | None, changes: list[dict[str, Any]], named: str
) -> None:
    original = on_disk(project)

    async with serve(build_harness(settings_root=project)) as client:
        answer = await client.post(FORM, json={"text": text or original, "changes": changes})

    assert (answer.status_code, answer.json()["code"]) == (422, "settings_edit_refused")
    detail = answer.json()["detail"]
    assert detail.split()[0] == named and "sometimes" not in detail and on_disk(project) == original


async def test_a_text_read_as_it_is_answers_its_settings_and_a_text_that_does_not_parse_answers_none(project: Path) -> None:
    async with serve(build_harness(settings_root=project)) as client:
        as_it_is = (await client.post(FORM, json={"text": on_disk(project)})).json()
        broken = (await client.post(FORM, json={"text": "trading:\n  order_mode: [mock_only\n", "changes": []})).json()

    assert as_it_is["text"] == on_disk(project) and as_it_is["values"]["environment"] == "dev"
    assert as_it_is["values"]["market.bond_etf_tax_exempt_until"] == "2026-12-31"
    assert (broken["text"], broken["values"]) == ("trading:\n  order_mode: [mock_only\n", None)


async def test_the_schema_says_what_each_setting_accepts_and_names_no_value_the_environment_owns(project: Path) -> None:
    async with serve(build_harness(settings_root=project)) as client:
        schema = (await client.post(FORM, json={"text": on_disk(project)})).json()["schema"]

    temperature, order_mode, offered = (
        schema_at(schema, path) for path in ("ai.temperature", "trading.order_mode", "ai.user_selectable")
    )
    assert (temperature["type"], temperature["minimum"], temperature["maximum"]) == ("number", 0, 2)
    assert "Claude refuses this setting" in temperature["description"]
    assert set(order_mode["enum"]) == {"mock_only", "live", "disabled"}
    assert offered["type"] == "array" and "$ref" in offered["items"]
    assert schema_at(schema, "accounts.registration_open")["type"] == "boolean"
    written = json.dumps(schema)
    for owned in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ACCOUNTS_KEY", "DB_PASSWORD", "SHIOAJI_API_KEY", "project_root"):
        assert owned not in written, owned


async def test_only_an_administrator_uses_the_form_and_only_from_the_web_app(project: Path) -> None:
    harness = build_harness(settings_root=project)
    harness.users.add(MEMBER, MEMBER_PASSWORD)
    body = {"text": on_disk(project), "changes": [change("ai.temperature", 0.4)]}

    async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as member:
        refused = await member.post(FORM, json=body)

    async with serve(harness) as administrator:
        no_header = await administrator.post(FORM, json=body, headers={"X-Requested-With": ""})

    assert (refused.status_code, refused.json()["code"], no_header.status_code) == (403, "administrators_only", 403)
