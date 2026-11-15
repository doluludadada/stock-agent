"""The administrator's settings form over HTTP, on a temporary copy of config/: never the repository's files."""

import asyncio
import json
import os
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
import support.harness
from support.databases import ENVIRONMENT, SERVER
from support.harness import (
    ADMINISTRATOR,
    ADMINISTRATOR_PASSWORD,
    MEMBER,
    MEMBER_PASSWORD,
    CliHarness,
    build_harness,
    harness_config,
    runtime_for,
)
from support.web import app_of, client_at, ended, hold_stock_list, serve, sign_in

from a_domain.ports.system.settings_files import SettingChange
from a_domain.types.enums import ExecutionProvider, FeatureVisibility, SettingsFile
from a_domain.types.errors import SettingsConflictError
from b_application.config.api_config import ApiConfig
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import settings_revision
from c_infrastructure.system.ordering_switch import SettingsFileOrderingSwitch
from d_presentation.dependencies import Runtime
from d_presentation.live_runtime import open_runtime_switch
from d_presentation.web.app import create_app

pytestmark = pytest.mark.asyncio

REPOSITORY_CONFIG = Path(__file__).resolve().parents[2] / "config"
SETTINGS = "/v1/admin/settings"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    A copy of config/, with the active AI provider's key and a placeholder ACCOUNTS_KEY set, so validation, which runs
    every check startup runs, does not depend on this machine's .env.
    """
    shutil.copytree(REPOSITORY_CONFIG, tmp_path / "config")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ACCOUNTS_KEY", "A" * 43)
    return tmp_path


def admin_harness(project: Path) -> CliHarness:
    return build_harness(settings_root=project)


def text_of(project: Path, file: SettingsFile = SettingsFile.APPSETTING) -> str:
    return (project / "config" / file.file_name).read_text(encoding="utf-8")


def write_by_hand(project: Path, old: str, new: str) -> None:
    assert old in text_of(project)
    (project / "config" / "appsetting.yaml").write_text(text_of(project).replace(old, new, 1), encoding="utf-8")


def line_of(text: str, needle: str) -> int:
    return text[: text.index(needle)].count("\n") + 1


def values_of(answer: httpx.Response) -> dict[str, Any]:
    """The form's values by path, from a GET or a PUT that answered it."""
    assert answer.status_code == 200, answer.text
    return {field["path"]: field["value"] for field in answer.json()}


async def save(client: httpx.AsyncClient, *changes: tuple[str, Any], password: str | None = ADMINISTRATOR_PASSWORD) -> httpx.Response:
    """A save as the settings page sends it, with the administrator's password unless the test leaves it out (None)."""
    body = {"confirm": True, "changes": [{"path": path, "value": value} for path, value in changes], "password": password}
    return await client.put(SETTINGS, json=body)


async def test_only_an_administrator_reads_the_settings_form_and_a_member_stays_signed_in(project: Path) -> None:
    harness = admin_harness(project)
    harness.users.add(MEMBER, MEMBER_PASSWORD)

    async with serve(harness, authorized=False) as signed_out:
        anonymous = await signed_out.get(SETTINGS)

    async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as member:
        refused = await member.get(SETTINGS)
        saved = await save(member, ("ai.temperature", 0.3))
        still_signed_in = await member.get("/v1/watchlist")

    async with serve(harness) as administrator:
        opened = await administrator.get(SETTINGS)

    assert (anonymous.status_code, refused.status_code, saved.status_code) == (401, 403, 403)
    assert (refused.json()["code"], still_signed_in.status_code, opened.status_code) == ("administrators_only", 200, 200)
    assert "temperature: 0.7\n" in text_of(project)


async def test_the_form_lists_every_setting_with_the_value_on_disk_and_never_a_secret(project: Path) -> None:
    async with serve(admin_harness(project)) as client:
        answer = await client.get(SETTINGS)

    fields = {field["path"]: field for field in answer.json()}
    assert fields["ai.temperature"] == {
        "path": "ai.temperature",
        "kind": "range",
        "group": "ai",
        "value": 0.7,
        "options": [],
        "steps": [],
        "minimum": 0.0,
        "maximum": 2.0,
        "step": 0.1,
        "unit": None,
        "nullable": False,
        "restart_only": False,
    }
    assert (fields["ai.available_models"]["kind"], fields["ai.available_models"]["value"]["claude"]) == (
        "structure",
        "claude-haiku-5-5",
    )
    assert (fields["environment"]["value"], fields["environment"]["restart_only"]) == ("dev", True)
    assert fields["ai.system_prompt"]["kind"] == "text" and fields["ai.system_prompt"]["value"].startswith("You are an expert")
    assert fields["api.valuation_cache_minutes"]["value"] == 15 and "\napi:" not in text_of(project)
    assert "test-key" not in answer.text and "A" * 43 not in answer.text and "api_key" not in answer.text


async def test_a_save_writes_the_change_in_place_backs_up_audits_without_values_and_runs_on_it_at_once(project: Path) -> None:
    original, harness = text_of(project), admin_harness(project)

    async with app_of(harness) as app, client_at(app) as client:
        switch = app.state.runtime_switch
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        before = switch.running[SettingsFile.APPSETTING]
        saved = await save(client, ("ai.temperature", 0.3))
        after = await client.get(SETTINGS)

        with switch.hold() as current:
            temperature = current.runtime.config.ai.temperature

    revision = settings_revision(text_of(project))
    assert values_of(saved)["ai.temperature"] == 0.3 and values_of(after)["ai.temperature"] == 0.3
    assert text_of(project) == original.replace("temperature: 0.7\n", "temperature: 0.3\n", 1) and temperature == 0.3
    assert switch.running[SettingsFile.APPSETTING] == revision != before
    reloaded = f"Settings saved from the Web and reloaded: appsetting.yaml {before[:12]} -> {revision[:12]}."
    assert ("info", reloaded) in harness.logger.records and ADMINISTRATOR_PASSWORD not in str(harness.logger.records)
    [backup] = (project / ".settings-admin" / "backups" / "appsetting").iterdir()
    assert backup.read_text(encoding="utf-8") == original
    for folder in (".settings-admin", ".settings-admin/backups", ".settings-admin/backups/appsetting"):
        assert (project / folder).stat().st_mode & 0o077 == 0, folder
    kept = (project / ".settings-admin" / "audit.jsonl").read_text(encoding="utf-8")
    entry = json.loads(kept)
    assert (entry["settings"], entry["actor"], entry["action"]) == (["ai.temperature"], "local", "save")
    assert "0.3" not in kept and ADMINISTRATOR.username not in kept


async def test_a_prompt_change_writes_instructions_yaml_and_leaves_appsetting_yaml_alone(project: Path) -> None:
    original, appsetting = text_of(project, SettingsFile.INSTRUCTIONS), text_of(project)
    prompt = "You are a careful analyst.\n\nAnswer in English.\n"

    async with app_of(admin_harness(project)) as app, client_at(app) as client:
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        saved = await save(client, ("ai.system_prompt", prompt))

        with app.state.runtime_switch.hold() as current:
            running = current.runtime.config.ai.system_prompt

    written = text_of(project, SettingsFile.INSTRUCTIONS)
    assert values_of(saved)["ai.system_prompt"] == prompt and running == prompt and text_of(project) == appsetting
    assert (
        written
        == "system_prompt: |\n  You are a careful analyst.\n\n  Answer in English.\n"
        + original[original.index("\nrag_injection_prompt:") :]
    )


async def test_a_save_that_changes_both_files_opens_one_runtime_on_both_and_audits_each_file(project: Path) -> None:
    harness, prompt = admin_harness(project), "Judge each post on {stock_id}.\n{posts_text}\n"

    async with app_of(harness) as app, client_at(app) as client:
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        saved = await save(client, ("ai.temperature", 0.3), ("prompts.social_sentiment", prompt))

        with app.state.runtime_switch.hold() as current:
            config = current.runtime.config

    reloads = [message for _, message in harness.logger.records if message.startswith("Settings saved from the Web")]
    entries = [json.loads(line) for line in (project / ".settings-admin" / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert values_of(saved)["prompts.social_sentiment"] == prompt
    assert (config.ai.temperature, config.prompts.social_sentiment) == (0.3, prompt)
    assert len(reloads) == 1 and "appsetting.yaml" in reloads[0] and "instructions.yaml" in reloads[0]
    assert [(entry["file"], entry["settings"]) for entry in entries] == [
        ("appsetting", ["ai.temperature"]),
        ("instructions", ["prompts.social_sentiment"]),
    ]


async def test_every_save_needs_the_password_in_the_same_request_and_a_wrong_one_keeps_the_session(project: Path) -> None:
    original = text_of(project)

    async with serve(admin_harness(project)) as client:
        without = await save(client, ("ai.temperature", 0.6), password=None)
        wrong = await save(client, ("ai.temperature", 0.6), password="not the password")
        still_signed_in = await client.get("/v1/auth/me")
        unchanged = text_of(project)
        right = await save(client, ("ai.temperature", 0.6))

    assert (without.status_code, without.json()["code"], wrong.status_code, wrong.json()["code"]) == (
        403,
        "password_required",
        403,
        "password_refused",
    )
    assert without.json()["detail"] == "Re-enter your password to save the settings. Nothing was saved."
    assert still_signed_in.status_code == 200 and unchanged == original and right.status_code == 200
    assert text_of(project) == original.replace("temperature: 0.7\n", "temperature: 0.6\n", 1)


@pytest.mark.parametrize(
    ("path", "value"),
    [("market.board_lot_shares", 1), ("accounts.settings_password_failures", 1000), ("trading.max_daily_buy_value", 30_000_000)],
    ids=["board-lot", "password-limit", "daily-buy-limit"],
)
async def test_a_stolen_session_alone_changes_no_setting(project: Path, path: str, value: Any) -> None:
    original = text_of(project)

    async with app_of(admin_harness(project)) as app, client_at(app) as client:
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        running = app.state.runtime_switch.running
        response = await save(client, (path, value), password=None)

    assert response.status_code == 403 and text_of(project) == original and app.state.runtime_switch.running == running


@pytest.mark.parametrize(
    ("path", "value", "code", "params"),
    [
        ("ai.temperature", 5, "less_than_equal", {"le": 2}),
        ("ai.active_model", "sometimes", "enum", {"expected": "'openai', 'grok', 'gemini', 'groq', 'nvidia' or 'claude'"}),
    ],
    ids=["out-of-range", "no-such-choice"],
)
async def test_a_value_the_app_would_refuse_is_never_saved_and_its_problem_is_at_its_setting(
    project: Path, path: str, value: Any, code: str, params: dict[str, Any]
) -> None:
    original = text_of(project)

    async with serve(admin_harness(project)) as client:
        response = await save(client, (path, value))

    [problem] = response.json()["problems"]
    assert (response.status_code, response.json()["code"]) == (422, "settings_refused")
    assert (problem["path"], problem["code"], problem["params"], problem["file"]) == (path, code, params, "appsetting")
    assert problem["line"] == line_of(original, f"{path.split('.')[-1]}:")
    assert text_of(project) == original and not (project / ".settings-admin").exists()


@pytest.mark.parametrize(("path", "value"), [("environment", "test"), ("audience", "public")], ids=["environment", "audience"])
async def test_a_save_that_changes_the_environment_or_the_audience_is_refused_until_a_restart(
    project: Path, path: str, value: str
) -> None:
    original = text_of(project)

    async with serve(admin_harness(project)) as client:
        response = await save(client, (path, value))

    [problem] = response.json()["problems"]
    assert (response.status_code, response.json()["code"], problem["path"]) == (422, "settings_refused", path)
    assert problem["message"].endswith(f"the {path} changes only when the app restarts") and text_of(project) == original


@pytest.mark.parametrize(
    ("path", "value"),
    [("ai.temperatur", 0.4), ("db.password", "Kq7x9-from-the-web"), ("ai", {"temperature": 0.4}), ("ai.temperature", True)],
    ids=["unknown", "secret", "section", "another-kind"],
)
async def test_a_change_the_form_cannot_write_is_refused_by_name_and_nothing_is_written(project: Path, path: str, value: Any) -> None:
    original = text_of(project)

    async with serve(admin_harness(project)) as client:
        response = await save(client, (path, value))

    assert (response.status_code, response.json()["code"]) == (422, "settings_edit_refused")
    assert response.json()["detail"].startswith(f"{path} ") and "Kq7x9" not in response.text and text_of(project) == original


async def test_a_change_to_the_value_a_field_shows_answers_the_form_and_writes_nothing(project: Path) -> None:
    original = text_of(project)

    async with app_of(admin_harness(project)) as app, client_at(app) as client:
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        running = app.state.runtime_switch.running
        response = await save(client, ("ai.temperature", 0.7), ("api.valuation_cache_minutes", 15))

    assert values_of(response)["ai.temperature"] == 0.7 and app.state.runtime_switch.running == running
    assert text_of(project) == original and not (project / ".settings-admin").exists()


async def test_each_refusal_says_which_it_is_by_a_stable_code(project: Path) -> None:
    harness = admin_harness(project)
    harness.users.add(MEMBER, MEMBER_PASSWORD)

    async with serve(harness) as client:
        required = await save(client, ("ai.temperature", 0.6), password=None)
        refused = await save(client, ("ai.temperature", 0.6), password="not the password")
        problems = await save(client, ("trading.max_order_value", 0))
        edit = await save(client, ("trading.order_mode", "live"))
        invalid = await client.put(SETTINGS, json={"confirm": True})

    async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as member:
        not_an_administrator = await member.get(SETTINGS)

    answers = (required, refused, not_an_administrator, problems, edit, invalid)
    assert [answer.status_code for answer in answers] == [403, 403, 403, 422, 422, 422]
    assert [answer.json()["code"] for answer in answers] == [
        "password_required",
        "password_refused",
        "administrators_only",
        "settings_refused",
        "settings_edit_refused",
        "invalid_request",
    ]


async def test_wrong_passwords_have_their_own_limit_and_never_lock_the_sign_in(project: Path) -> None:
    harness = admin_harness(project)
    limit = harness.config.accounts.settings_password_failures

    async with serve(harness) as client:
        wrong = [(await save(client, ("trading.max_order_value", 90000), password="guess")).status_code for _ in range(limit + 1)]
        throttled = await save(client, ("trading.max_order_value", 90000))
        signed_in = await client.post(
            "/v1/auth/sign-in", json={"identifier": ADMINISTRATOR.username, "password": ADMINISTRATOR_PASSWORD}
        )

    assert wrong == [403] * limit + [429] and throttled.status_code == 429 and "Retry-After" in throttled.headers
    assert throttled.json()["code"] == "sign_in_throttled" and signed_in.status_code == 200
    assert "max_order_value: 100000" in text_of(project)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("api.allowed_hosts", ["admin.example"]),
        ("sources.ai.nvidia_base_url", "https://attacker.example/v1"),
        ("db.chroma_persist_path", "elsewhere"),
        ("market.stock_ticks", {"0": "1"}),
    ],
    ids=["hosts", "ai-base-url", "chroma-folder", "ticks"],
)
async def test_a_setting_only_an_operator_changes_is_not_on_the_form_and_a_save_that_names_it_writes_nothing(
    project: Path, path: str, value: Any
) -> None:
    original = text_of(project)

    async with serve(admin_harness(project)) as client:
        response = await save(client, ("ai.temperature", 0.6), (path, value))
        form = await client.get(SETTINGS)

    assert (response.status_code, response.json()["code"]) == (422, "settings_edit_refused")
    assert response.json()["detail"].startswith(f"{path} ") and "attacker" not in response.text
    assert text_of(project) == original and not (project / ".settings-admin").exists()
    assert path not in values_of(form) and values_of(form)["ai.temperature"] == 0.7


async def test_a_prompt_too_large_for_the_editor_is_refused_not_failed(project: Path) -> None:
    async with serve(admin_harness(project)) as client:
        response = await save(client, ("ai.system_prompt", "x" * 300_000))

    [problem] = response.json()["problems"]
    assert (response.status_code, problem["path"]) == (422, "api.settings_file_max_bytes")
    assert "is smaller than instructions.yaml" in problem["message"]


@pytest.mark.parametrize(
    ("strategy_id", "message"),
    [
        ("../../../../../../../etc/stock-agent-probe", "is not a built-in strategy id: lowercase letters, digits and underscores"),
        ("absent_strategy", "names no built-in strategy in config/strategies"),
    ],
    ids=["path-outside-config", "missing"],
)
async def test_a_built_in_strategy_id_is_checked_before_it_names_a_file_and_no_server_path_is_shown(
    project: Path, strategy_id: str, message: str
) -> None:
    async with serve(admin_harness(project)) as client:
        response = await save(client, ("technical.built_in_strategies", ["balanced", strategy_id]))

    [problem] = response.json()["problems"]
    assert (problem["path"], problem["message"]) == ("technical.built_in_strategies.1", message)
    assert str(project) not in response.text and "Errno" not in response.text


def alias_bomb(levels: int, width: int) -> str:
    """The review's probe: each level an anchored mapping of `width` aliases of the level below, width**levels values."""
    lines = ["l0: &l0 {x: 1}"]
    for level in range(1, levels + 1):
        lines.append(f"l{level}: &l{level} {{{', '.join(f'k{index}: *l{level - 1}' for index in range(width))}}}")
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    ("text", "message", "line", "column"),
    [
        (alias_bomb(4, 10), "YAML anchors and aliases are not allowed in a settings file", 1, 5),
        ("trading:\n  max_order_value: [100000\n", None, 3, 1),
    ],
    ids=["alias-bomb", "does-not-parse"],
)
async def test_a_settings_file_that_does_not_parse_answers_where_it_stops_and_the_form_writes_nothing_into_it(
    project: Path, text: str, message: str | None, line: int, column: int
) -> None:
    async with serve(admin_harness(project)) as client:
        (project / "config" / "appsetting.yaml").write_text(text, encoding="utf-8")
        read = await client.get(SETTINGS)
        saved = await save(client, ("ai.temperature", 0.3))

    [problem] = read.json()["problems"]
    assert (read.status_code, read.json()["code"]) == (422, "settings_refused")
    assert (problem["file"], problem["line"], problem["column"]) == ("appsetting", line, column)
    assert message is None or problem["message"] == message
    assert (saved.status_code, saved.json()["code"]) == (422, "settings_edit_refused") and text_of(project) == text


async def test_a_symlinked_settings_file_is_never_read_or_written(project: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    outside = tmp_path_factory.mktemp("outside") / "appsetting.yaml"
    outside.write_text(text_of(project), encoding="utf-8")
    (project / "config" / "appsetting.yaml").unlink()
    os.symlink(outside, project / "config" / "appsetting.yaml")

    async with serve(admin_harness(project)) as client:
        response = await client.get(SETTINGS)
        saved = await save(client, ("ai.temperature", 0.3))

    assert (response.status_code, saved.status_code) == (403, 403)
    assert response.json() == {"detail": "appsetting.yaml is not a regular file inside config/", "code": "settings_file_refused"}
    assert outside.read_text(encoding="utf-8") == text_of(project)


@pytest.mark.parametrize(
    ("damage", "code", "detail"),
    [
        (lambda path: path.unlink(), 404, "appsetting.yaml is missing from config/."),
        (lambda path: path.write_text(f"# {'x' * 300_000}\n", encoding="utf-8"), 403, "appsetting.yaml is larger than 262144 bytes"),
    ],
)
async def test_a_missing_or_oversized_settings_file_says_so(project: Path, damage, code: int, detail: str) -> None:
    harness = admin_harness(project)
    damage(project / "config" / "appsetting.yaml")

    async with serve(harness) as client:
        response = await client.get(SETTINGS)

    assert (response.status_code, response.json()["detail"]) == (code, detail)


async def test_a_save_during_a_running_run_applies_at_once_and_the_run_finishes_on_the_runtime_it_started_on(project: Path) -> None:
    harness = admin_harness(project)
    release = hold_stock_list(harness)

    async with app_of(harness) as app, client_at(app) as client:
        switch = app.state.runtime_switch
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        run = (await client.post("/v1/runs/full-cycle", json={"confirm": True})).json()["run_id"]
        saved = await save(client, ("ai.temperature", 0.2))

        with switch.hold() as current:
            temperature = current.runtime.config.ai.temperature

        held_by_the_run = [opened.closing is None for opened in switch.opened]
        release.set()
        finished = await ended(client, run)

        for _ in range(1000):
            if all(opened.closing is not None and opened.closing.done() for opened in switch.opened[:-1]):
                break
            await asyncio.sleep(0)

        assert (values_of(saved)["ai.temperature"], temperature, held_by_the_run) == (0.2, 0.2, [True, True])
        assert finished["state"] == "finished" and switch.opened[0].closing is not None and switch.opened[0].closing.done()


async def test_a_save_of_the_run_cap_applies_to_the_next_run_started(project: Path) -> None:
    harness = admin_harness(project)
    harness.users.add(MEMBER, MEMBER_PASSWORD)
    release = hold_stock_list(harness)

    async with app_of(harness) as app, client_at(app) as administrator, client_at(app, "127.0.0.2") as member:
        assert (await sign_in(administrator, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        assert (await sign_in(member, MEMBER.username, MEMBER_PASSWORD)).status_code == 200
        saved = await save(administrator, ("accounts.max_concurrent_runs", 1), ("features.full_cycle", "everyone"))
        running = await administrator.post("/v1/runs/full-cycle", json={"confirm": True})
        refused = await member.post("/v1/runs/full-cycle", json={"confirm": True})
        release.set()
        await ended(administrator, running.json()["run_id"])

    assert (values_of(saved)["accounts.max_concurrent_runs"], running.status_code, refused.status_code) == (1, 202, 429)


async def test_a_log_level_changed_in_the_file_applies_at_the_reload(project: Path) -> None:
    harness = admin_harness(project)

    async with app_of(harness) as app:
        write_by_hand(project, "log_level: INFO", "log_level: WARNING")
        await app.state.runtime_switch.reload()

    assert harness.logger.level == "WARNING"


async def test_a_save_whose_audit_entry_cannot_be_written_changes_neither_the_file_nor_the_running_app(project: Path) -> None:
    (project / ".settings-admin" / "audit.jsonl").mkdir(parents=True)
    original = text_of(project)

    async with app_of(admin_harness(project)) as app, client_at(app) as client:
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        running = app.state.runtime_switch.running

        with pytest.raises(IsADirectoryError):
            await save(client, ("ai.temperature", 0.2))

        after = await client.get(SETTINGS)

    assert text_of(project) == original and app.state.runtime_switch.running == running
    assert values_of(after)["ai.temperature"] == 0.7


async def test_a_save_on_settings_the_server_no_longer_runs_is_a_conflict(project: Path) -> None:
    async with app_of(admin_harness(project)) as app:
        switch = app.state.runtime_switch

        with switch.hold() as stale:
            write_by_hand(project, "temperature: 0.7", "temperature: 0.2")
            await switch.reload()
            change = SettingChange(path="ai.temperature", value=0.3)

            with pytest.raises(SettingsConflictError):
                await switch.save(stale, ADMINISTRATOR, [change], password=None, client="127.0.0.1", host="127.0.0.1")

    assert "temperature: 0.2\n" in text_of(project) and not (project / ".settings-admin").exists()


async def test_a_file_another_editor_saves_while_the_new_settings_open_is_a_conflict_and_nothing_is_written(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def edited_meanwhile(harness: CliHarness, config: AppConfig) -> Runtime:
        write_by_hand(project, "# config/appsetting.yaml", "# saved by another editor")
        return runtime_for(harness, config)

    async with serve(admin_harness(project)) as client:
        monkeypatch.setattr(support.harness, "runtime_for", edited_meanwhile)
        response = await save(client, ("ai.temperature", 0.3))

    assert (response.status_code, response.json()["code"]) == (409, "settings_conflict")
    assert "# saved by another editor" in text_of(project) and "temperature: 0.7\n" in text_of(project)
    assert not (project / ".settings-admin").exists()


async def test_a_saved_sinopac_limit_holds_the_runs_that_start_after_it(project: Path) -> None:
    async with app_of(admin_harness(project)) as app, client_at(app) as client:
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        saved = await save(client, ("trading.max_order_value", 50000))
        brokers = (await client.get("/v1/account/brokers")).json()

        with app.state.runtime_switch.hold() as current:
            limits = current.runtime.config.broker_access_rule().limit_rule

    assert values_of(saved)["trading.max_order_value"] == 50000
    assert (limits.max_order_value, limits.max_daily_buy_value) == (50_000, 300_000)
    assert [broker["broker"] for broker in brokers] == ["mock"]
    entry = json.loads((project / ".settings-admin" / "audit.jsonl").read_text(encoding="utf-8"))
    assert entry["settings"] == ["trading.max_order_value"]


@pytest.fixture
def real_project(project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The project copy served by the real opener: Chroma inside it, the session's database, no .env."""
    monkeypatch.chdir(project)
    write_by_hand(project, 'chroma_persist_path: "chroma_data"', f'chroma_persist_path: "{project / "chroma"}"')
    return project


async def set_up_and_sign_in(app, client) -> None:
    body = {"username": "owner", "email": "owner@example.com", "password": ADMINISTRATOR_PASSWORD, "setup_code": app.state.setup_code}
    assert (await client.post("/v1/auth/setup", json=body)).status_code == 201
    assert (await sign_in(client, "owner", ADMINISTRATOR_PASSWORD)).status_code == 200


async def test_a_database_that_cannot_be_reached_refuses_the_save_writes_nothing_and_never_shows_the_connection(
    real_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(lambda: open_runtime_switch(real_project))

    async with app.router.lifespan_context(app), client_at(app) as client:
        await set_up_and_sign_in(app, client)
        for name, value in {
            "DB_USER": "owner",
            "DB_PASSWORD": "Kq7x9-secret",
            "DB_HOST": "127.0.0.1",
            "DB_PORT": "9",
            "DB_NAME": "absent",
        }.items():
            monkeypatch.setenv(name, value)
        text = text_of(real_project)
        response = await save(client, ("ai.temperature", 0.6))
        after = await client.get("/v1/auth/me")

    [problem] = response.json()["problems"]
    assert response.status_code == 422 and problem["message"].startswith("The app would not start: ")
    assert "Kq7x9" not in response.text and "127.0.0.1" not in response.text and after.status_code == 200
    assert text_of(real_project) == text and not (real_project / ".settings-admin").exists()


@asynccontextmanager
async def another_empty_database() -> AsyncIterator[str]:
    """The name of a second database on the tests' server, which holds no table and no account, dropped afterwards."""
    name = f"{ENVIRONMENT['DB_NAME']}_other"
    server = await asyncpg.connect(database="postgres", **SERVER)

    try:
        await server.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await server.execute(f'CREATE DATABASE "{name}"')
        yield name
    finally:
        await server.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await server.close()


async def test_a_database_with_no_account_of_the_saving_administrator_is_refused(
    real_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(lambda: open_runtime_switch(real_project))

    async with app.router.lifespan_context(app), client_at(app) as client, another_empty_database() as other:
        await set_up_and_sign_in(app, client)
        monkeypatch.setenv("DB_NAME", other)
        text = text_of(real_project)
        response = await save(client, ("ai.temperature", 0.6))

    assert response.status_code == 422 and text_of(real_project) == text
    assert "no active administrator account of yours" in response.json()["problems"][0]["message"]


async def test_an_edit_on_disk_is_picked_up_by_the_watcher_and_the_form_shows_it(project: Path) -> None:
    config = harness_config().model_copy(update={"api": ApiConfig(settings_poll_seconds=0.05)})
    harness = build_harness(config=config, settings_root=project)

    async with app_of(harness) as app, client_at(app) as client:
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        write_by_hand(project, "temperature: 0.7", "temperature: 0.2")
        disk = settings_revision(text_of(project))

        for _ in range(200):
            if app.state.runtime_switch.running[SettingsFile.APPSETTING] == disk:
                break
            await asyncio.sleep(0.02)

        with app.state.runtime_switch.hold() as current:
            assert current.runtime.config.ai.temperature == 0.2

        assert values_of(await client.get(SETTINGS))["ai.temperature"] == 0.2


# ------------------------- turning SinoPac ordering off counts whatever becomes of the rest of the save ------------------------- #

ORDERING_ON, ORDERING_OFF = "sinopac_ordering: administrators", 'sinopac_ordering: "off"'
SHIOAJI = ExecutionProvider.SHIOAJI


@pytest.fixture
def ordering_project(project: Path) -> Path:
    """The project copy of a site whose administrators order on SinoPac."""
    write_by_hand(project, ORDERING_OFF, ORDERING_ON)
    return project


async def test_ordering_turned_off_is_written_although_another_change_of_the_same_save_is_refused(ordering_project: Path) -> None:
    switch = SettingsFileOrderingSwitch(ordering_project)

    async with serve(admin_harness(ordering_project)) as client:
        before = await switch.visibility(SHIOAJI)
        refused = await save(client, ("features.sinopac_ordering", "off"), ("ai.temperature", 99))

    assert before == FeatureVisibility.ADMINISTRATORS
    assert (refused.status_code, refused.json()["code"]) == (422, "settings_refused")
    assert ORDERING_ON not in text_of(ordering_project) and "temperature: 0.7\n" in text_of(ordering_project)
    assert await switch.visibility(SHIOAJI) == FeatureVisibility.OFF


async def test_ordering_turned_off_is_written_although_the_app_does_not_start_on_the_new_settings(
    ordering_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def does_not_start(harness: CliHarness, config: AppConfig) -> Runtime:
        raise RuntimeError("the new settings' runtime did not open")

    async with serve(admin_harness(ordering_project)) as client:
        monkeypatch.setattr(support.harness, "runtime_for", does_not_start)
        refused = await save(client, ("features.sinopac_ordering", "off"), ("ai.temperature", 0.3))

    assert (refused.status_code, refused.json()["code"]) == (422, "settings_refused")
    assert ORDERING_ON not in text_of(ordering_project) and "temperature: 0.7\n" in text_of(ordering_project)
    assert await SettingsFileOrderingSwitch(ordering_project).visibility(SHIOAJI) == FeatureVisibility.OFF


async def test_ordering_is_not_turned_off_by_a_save_the_administrator_did_not_confirm(ordering_project: Path) -> None:
    async with serve(admin_harness(ordering_project)) as client:
        unconfirmed = await save(client, ("features.sinopac_ordering", "off"), password=None)
        wrong = await save(client, ("features.sinopac_ordering", "off"), password="not the password")

    assert (unconfirmed.json()["code"], wrong.json()["code"]) == ("password_required", "password_refused")
    assert ORDERING_ON in text_of(ordering_project)


async def test_a_save_that_only_turns_ordering_off_runs_on_it_at_once(ordering_project: Path) -> None:
    async with app_of(admin_harness(ordering_project)) as app, client_at(app) as client:
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        saved = await save(client, ("features.sinopac_ordering", "off"))
        running = app.state.runtime_switch.opened[-1].runtime.config.features.sinopac_ordering

    assert values_of(saved)["features.sinopac_ordering"] == "off"
    assert running == FeatureVisibility.OFF and ORDERING_ON not in text_of(ordering_project)


# ------------------------------- the settings files on disk are the switch every process asks ------------------------------- #


async def test_the_switch_is_what_the_settings_on_disk_say_at_each_ask_and_off_while_they_do_not_say(ordering_project: Path) -> None:
    switch, other_process = SettingsFileOrderingSwitch(ordering_project), SettingsFileOrderingSwitch(ordering_project)
    on = (await switch.visibility(SHIOAJI), await other_process.visibility(SHIOAJI))

    write_by_hand(ordering_project, ORDERING_ON, ORDERING_OFF)
    off = (await switch.visibility(SHIOAJI), await other_process.visibility(SHIOAJI))

    write_by_hand(ordering_project, f"  {ORDERING_OFF}\n", "")
    unset = await switch.visibility(SHIOAJI)

    write_by_hand(ordering_project, "temperature: 0.7", f"temperature: 99\n  {ORDERING_ON}")
    not_loadable = await switch.visibility(SHIOAJI)

    assert on == (FeatureVisibility.ADMINISTRATORS, FeatureVisibility.ADMINISTRATORS)
    assert off == (FeatureVisibility.OFF, FeatureVisibility.OFF)
    assert (unset, not_loadable) == (FeatureVisibility.OFF, FeatureVisibility.OFF)
