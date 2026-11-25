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
from support.databases import ENVIRONMENT, SERVER, TestDatabase, as_superuser
from support.fakes import FakeTradingJournal
from support.harness import (
    ADMINISTRATOR,
    ADMINISTRATOR_PASSWORD,
    MARKET_OPEN,
    MEMBER,
    MEMBER_PASSWORD,
    CliHarness,
    build_harness,
    harness_config,
    runtime_for,
)
from support.settings import sinopac_setup
from support.web import app_of, client_at, ended, hold_stock_list, serve, sign_in

from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.order import Order
from a_domain.ports.system.settings_files import SettingChange
from a_domain.types.enums import (
    ExecutionProvider,
    FeatureVisibility,
    OrderType,
    SettingsFile,
    ShioajiServer,
    SystemEnvironment,
    TimeInForce,
    TradeAction,
    Workflow,
)
from a_domain.types.errors import SettingsConflictError
from a_domain.types.ids import new_decision_id
from b_application.config.api_config import ApiConfig
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import settings_revision
from b_application.pipeline import Pipeline
from c_infrastructure.system.ordering_switch import SettingsFileOrderingSwitch
from d_presentation.dependencies import Runtime
from d_presentation.live_runtime import ReloadRefused, open_runtime_switch
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
    [("market.board_lot_shares", 1), ("accounts.settings_password_failures", 1000), ("trading.max_daily_buy_equity_pct", 3.0)],
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
        problems = await save(client, ("trading.max_order_equity_pct", 0))
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
        wrong = [(await save(client, ("trading.max_order_equity_pct", 0.2), password="guess")).status_code for _ in range(limit + 1)]
        throttled = await save(client, ("trading.max_order_equity_pct", 0.2))
        signed_in = await client.post(
            "/v1/auth/sign-in", json={"identifier": ADMINISTRATOR.username, "password": ADMINISTRATOR_PASSWORD}
        )

    assert wrong == [403] * limit + [429] and throttled.status_code == 429 and "Retry-After" in throttled.headers
    assert throttled.json()["code"] == "sign_in_throttled" and signed_in.status_code == 200
    assert "max_order_equity_pct: 0.25" in text_of(project)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("api.allowed_hosts", ["admin.example"]),
        ("sources.ai.nvidia_base_url", "https://attacker.example/v1"),
        ("folder.embedding_model_dir", "elsewhere"),
        ("market.stock_ticks", {"0": "1"}),
    ],
    ids=["hosts", "ai-base-url", "model-folder", "ticks"],
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
        ("trading:\n  max_order_equity_pct: [0.25\n", None, 3, 1),
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
        saved = await save(client, ("trading.max_order_equity_pct", 0.2))
        brokers = (await client.get("/v1/account/brokers")).json()

        with app.state.runtime_switch.hold() as current:
            limits = current.runtime.config.broker_access_rule().limit_rule

    assert values_of(saved)["trading.max_order_equity_pct"] == 0.2
    assert (limits.max_order_equity_pct, limits.max_daily_buy_equity_pct) == (0.2, 1.1)
    assert [broker["broker"] for broker in brokers] == ["mock"]
    entry = json.loads((project / ".settings-admin" / "audit.jsonl").read_text(encoding="utf-8"))
    assert entry["settings"] == ["trading.max_order_equity_pct"]


@pytest.fixture
def real_project(project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The project copy served by the real opener: the session's database, no .env."""
    monkeypatch.chdir(project)
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
async def another_empty_database(superuser: str) -> AsyncIterator[str]:
    """
    The name of a second database on the tests' server, which holds no table and no account but the vector extension,
    as `superuser` creates it, dropped afterwards.
    """
    name = f"{ENVIRONMENT['DB_NAME']}_other"
    server = await asyncpg.connect(database="postgres", **SERVER)

    try:
        await server.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await server.execute(f'CREATE DATABASE "{name}"')
        await as_superuser(superuser, name, "CREATE EXTENSION vector")
        yield name
    finally:
        await server.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await server.close()


async def test_a_database_with_no_account_of_the_saving_administrator_is_refused(
    real_project: Path, monkeypatch: pytest.MonkeyPatch, test_database: TestDatabase
) -> None:
    app = create_app(lambda: open_runtime_switch(real_project))

    async with app.router.lifespan_context(app), client_at(app) as client, another_empty_database(test_database.superuser) as other:
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


async def sinopac_switch(switch: SettingsFileOrderingSwitch) -> tuple[FeatureVisibility, ShioajiServer] | None:
    """What one read of the ordering switch says of SinoPac: whom it lets order and the server; None for files that do not load."""
    read = await switch.read()
    return (read.ordering[SHIOAJI], read.server) if read is not None else None


async def test_ordering_turned_off_is_written_although_another_change_of_the_same_save_is_refused(ordering_project: Path) -> None:
    switch = SettingsFileOrderingSwitch(ordering_project)

    async with serve(admin_harness(ordering_project)) as client:
        before = await sinopac_switch(switch)
        refused = await save(client, ("features.sinopac_ordering", "off"), ("ai.temperature", 99))

    assert before == (FeatureVisibility.ADMINISTRATORS, ShioajiServer.SIMULATION)
    assert (refused.status_code, refused.json()["code"]) == (422, "settings_refused")
    assert ORDERING_ON not in text_of(ordering_project) and "temperature: 0.7\n" in text_of(ordering_project)
    assert await sinopac_switch(switch) == (FeatureVisibility.OFF, ShioajiServer.SIMULATION)


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
    assert await sinopac_switch(SettingsFileOrderingSwitch(ordering_project)) == (FeatureVisibility.OFF, ShioajiServer.SIMULATION)


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


# ------------------------- switching SinoPac's server is a save that turns SinoPac ordering off ------------------------- #

SIMULATION_SERVER, PRODUCTION_SERVER = "  server: simulation", "  server: production"


@pytest.fixture
def server_project(ordering_project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    The owner's server: environment test, administrators ordering on SinoPac's simulation server, and both key sets in
    the environment, each variable set to its own name.
    """
    write_by_hand(ordering_project, "environment: dev", "environment: test")
    monkeypatch.chdir(ordering_project)

    for credential in (*ShioajiServer.SIMULATION.credentials, *ShioajiServer.PRODUCTION.credentials):
        monkeypatch.setenv(credential.value, credential.value)

    return ordering_project


def server_harness(project: Path, environment: SystemEnvironment = SystemEnvironment.TEST) -> CliHarness:
    """The harness of a site in `environment` whose runtime runs on SinoPac's simulation server."""
    return build_harness(config=sinopac_setup(harness_config(), ShioajiServer.SIMULATION, environment), settings_root=project)


async def test_a_switch_of_the_server_writes_ordering_off_before_the_server_and_runs_on_the_new_server_at_once(
    server_project: Path,
) -> None:
    async with app_of(server_harness(server_project)) as app, client_at(app) as client:
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        saved = await save(client, ("shioaji.server", "production"), ("features.sinopac_ordering", "off"))
        running = app.state.runtime_switch.opened[-1].runtime.config

    assert values_of(saved)["shioaji.server"] == "production"
    assert (running.shioaji.server, running.features.sinopac_ordering) == (ShioajiServer.PRODUCTION, FeatureVisibility.OFF)
    assert PRODUCTION_SERVER in text_of(server_project) and ORDERING_ON not in text_of(server_project)
    first, then = [
        json.loads(line) for line in (server_project / ".settings-admin" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert first["settings"] == ["features.sinopac_ordering"], "ordering is off on disk before the files name the new server"
    assert "shioaji.server" in then["settings"]
    assert await sinopac_switch(SettingsFileOrderingSwitch(server_project)) == (FeatureVisibility.OFF, ShioajiServer.PRODUCTION)


@pytest.mark.parametrize(
    "changes",
    [(("shioaji.server", "production"),), (("shioaji.server", "production"), ("features.sinopac_ordering", "administrators"))],
    ids=["server-alone", "ordering-kept-on"],
)
async def test_a_switch_of_the_server_that_leaves_ordering_on_is_refused_with_nothing_written(
    server_project: Path, changes: tuple[tuple[str, str], ...]
) -> None:
    text = text_of(server_project)

    async with serve(server_harness(server_project)) as client:
        refused = await save(client, *changes)

    [problem] = refused.json()["problems"]
    assert (refused.status_code, problem["path"]) == (422, "shioaji.server")
    assert "turns features.sinopac_ordering off in the same save" in problem["message"]
    assert text_of(server_project) == text and not (server_project / ".settings-admin").exists()


async def test_a_switch_to_production_while_a_production_variable_is_unset_is_refused_naming_it_and_leaves_ordering_off(
    server_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SHIOAJI_CA_PATH")
    monkeypatch.setenv("SHIOAJI_PERSON_ID", " ")

    async with serve(server_harness(server_project)) as client:
        refused = await save(client, ("shioaji.server", "production"), ("features.sinopac_ordering", "off"))

    [problem] = refused.json()["problems"]
    assert (refused.status_code, problem["path"]) == (422, "shioaji.server")
    assert problem["message"] == (
        "shioaji.server production needs SHIOAJI_CA_PATH, SHIOAJI_PERSON_ID in the server's environment or .env"
    )
    assert "SHIOAJI_CA_PASSWORD" not in refused.text, "a variable that is set is never named, and no value ever is"
    assert await sinopac_switch(SettingsFileOrderingSwitch(server_project)) == (FeatureVisibility.OFF, ShioajiServer.SIMULATION), (
        "the switch is refused, the turn-off holds"
    )


async def test_a_switch_to_production_while_registration_is_open_is_refused_and_leaves_ordering_off(server_project: Path) -> None:
    write_by_hand(server_project, "registration_open: false", "registration_open: true")
    harness = server_harness(server_project)

    async with serve(harness) as client:
        refused = await save(client, ("shioaji.server", "production"), ("features.sinopac_ordering", "off"))

    [problem] = refused.json()["problems"]
    assert (refused.status_code, problem["path"]) == (422, "accounts.registration_open")
    assert await sinopac_switch(SettingsFileOrderingSwitch(server_project)) == (FeatureVisibility.OFF, ShioajiServer.SIMULATION)


async def test_a_developers_machine_refuses_a_switch_to_production_and_leaves_ordering_off(
    ordering_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ordering_project)

    async with serve(server_harness(ordering_project, SystemEnvironment.DEV)) as client:
        refused = await save(client, ("shioaji.server", "production"), ("features.sinopac_ordering", "off"))

    problems = {problem["path"]: problem["message"] for problem in refused.json()["problems"]}
    assert refused.status_code == 422
    assert problems["shioaji.server"] == "the environment this machine runs in does not log in to SinoPac's production server"
    assert await sinopac_switch(SettingsFileOrderingSwitch(ordering_project)) == (FeatureVisibility.OFF, ShioajiServer.SIMULATION)


async def test_a_refused_switch_of_the_server_shows_ordering_off_at_once(
    server_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refused save's turn-off of ordering, written first, is what the SinoPac page and the run's brokers answer next."""
    monkeypatch.delenv("SHIOAJI_CA_PATH")

    async with serve(server_harness(server_project)) as client:
        before = (await client.get("/v1/account/brokerage")).json()
        refused = await save(client, ("shioaji.server", "production"), ("features.sinopac_ordering", "off"))
        after = (await client.get("/v1/account/brokerage")).json()
        brokers = (await client.get("/v1/account/brokers")).json()

    assert (before["ordering"], refused.status_code) == (True, 422)
    assert ORDERING_ON not in text_of(server_project)
    assert (after["ordering"], after["server"]) == (False, "simulation")
    assert after["switch_refusal"] == {
        "reason": "credentials_missing",
        "server": "production",
        "missing": ["SHIOAJI_CA_PATH"],
        "unsettled": 0,
    }
    assert [broker["broker"] for broker in brokers] == ["mock"]


def awaiting_settlement(harness: CliHarness) -> None:
    """A SinoPac BUY of an ended manual BUY run of the administrator whose answer was lost, so it awaits settlement."""
    run = SystemStats(workflow=Workflow.MANUAL_BUY, execution_provider=ExecutionProvider.SHIOAJI, start_time=MARKET_OPEN)
    run.finish(now=MARKET_OPEN)
    order = Order(
        run_id=run.run_id,
        decision_id=new_decision_id(),
        stock_id="2330",
        action=TradeAction.BUY,
        order_type=OrderType.LIMIT,
        quantity=1000,
        limit_price=100.0,
        price_at_signal=100.0,
        time_in_force=TimeInForce.IOC,
        created_at=MARKET_OPEN,
        updated_at=MARKET_OPEN,
    )
    order.leave_unconfirmed("the broker's answer was lost", now=MARKET_OPEN)
    journal = harness.journal
    assert isinstance(journal, FakeTradingJournal)
    journal.runs[run.run_id], journal.orders[order.id] = run, order


async def test_a_switch_of_the_server_while_a_sinopac_order_awaits_settlement_is_refused_and_the_page_says_how_many(
    server_project: Path,
) -> None:
    config = sinopac_setup(harness_config(), ShioajiServer.SIMULATION, SystemEnvironment.TEST)
    closed = config.model_copy(update={"accounts": config.accounts.model_copy(update={"registration_open": False})})
    harness = build_harness(config=closed, settings_root=server_project)
    awaiting_settlement(harness)

    async with serve(harness) as client:
        page = (await client.get("/v1/account/brokerage")).json()
        refused = await save(client, ("shioaji.server", "production"), ("features.sinopac_ordering", "off"))

    problems = {problem["path"]: problem["message"] for problem in refused.json()["problems"]}
    assert page["switch_refusal"] == {"reason": "orders_unsettled", "server": "production", "missing": [], "unsettled": 1}
    assert refused.status_code == 422
    assert problems["shioaji.server"].startswith("1 SinoPac order awaits settlement from the record of the server")
    assert problems["shioaji.server"].endswith("at the latest the next day"), "an order of an earlier day needs no login to fail"
    assert await sinopac_switch(SettingsFileOrderingSwitch(server_project)) == (FeatureVisibility.OFF, ShioajiServer.SIMULATION)


async def test_a_reload_from_disk_that_switches_the_server_while_a_sinopac_order_awaits_settlement_is_refused(
    server_project: Path,
) -> None:
    """The settings watcher and the CLI's reload open the edited files as a save does, and count the orders as it does."""
    harness = server_harness(server_project)
    awaiting_settlement(harness)

    async with app_of(harness) as app:
        switch = app.state.runtime_switch
        write_by_hand(server_project, ORDERING_ON, ORDERING_OFF)
        write_by_hand(server_project, SIMULATION_SERVER, PRODUCTION_SERVER)
        reloaded = await switch.reload()
        running = switch.opened[-1].runtime.config.shioaji.server

    assert isinstance(reloaded, ReloadRefused) and running == ShioajiServer.SIMULATION
    assert [(problem.path, problem.message[:42]) for problem in reloaded.problems] == [
        ("shioaji.server", "1 SinoPac order awaits settlement from the")
    ]


async def test_a_save_of_the_server_is_refused_at_its_publish_when_an_order_came_to_await_settlement_after_its_review(
    server_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_by_hand(server_project, ORDERING_ON, ORDERING_OFF)
    harness = server_harness(server_project)
    confirm = Pipeline.confirm_settings_save

    async def confirmed_while_an_answer_is_lost(pipeline: Pipeline, *args: Any) -> None:
        await confirm(pipeline, *args)
        awaiting_settlement(harness)

    monkeypatch.setattr(Pipeline, "confirm_settings_save", confirmed_while_an_answer_is_lost)
    text = text_of(server_project)

    async with serve(harness) as client:
        refused = await save(client, ("shioaji.server", "production"))

    assert refused.status_code == 422
    assert [problem["path"] for problem in refused.json()["problems"]] == ["shioaji.server"]
    assert text_of(server_project) == text


async def test_a_switch_back_to_simulation_turns_ordering_off_too(server_project: Path) -> None:
    write_by_hand(server_project, SIMULATION_SERVER, PRODUCTION_SERVER)
    harness = build_harness(
        config=sinopac_setup(harness_config(), ShioajiServer.PRODUCTION, SystemEnvironment.TEST), settings_root=server_project
    )

    async with serve(harness) as client:
        refused = await save(client, ("shioaji.server", "simulation"))
        saved = await save(client, ("shioaji.server", "simulation"), ("features.sinopac_ordering", "off"))

    assert refused.status_code == 422 and saved.status_code == 200
    assert SIMULATION_SERVER in text_of(server_project) and ORDERING_ON not in text_of(server_project)


async def test_a_save_that_keeps_the_server_changes_nothing_about_ordering(server_project: Path) -> None:
    async with serve(server_harness(server_project)) as client:
        saved = await save(client, ("shioaji.server", "simulation"), ("ai.temperature", 0.3))

    assert saved.status_code == 200 and ORDERING_ON in text_of(server_project) and "temperature: 0.3\n" in text_of(server_project)


# ------------------------------- the settings files on disk are the switch every process asks ------------------------------- #


async def test_the_switch_is_what_the_settings_on_disk_say_at_each_ask_and_lets_nobody_order_while_they_do_not_say(
    ordering_project: Path,
) -> None:
    switch, other_process = SettingsFileOrderingSwitch(ordering_project), SettingsFileOrderingSwitch(ordering_project)
    on = (await sinopac_switch(switch), await sinopac_switch(other_process))

    write_by_hand(ordering_project, ORDERING_ON, ORDERING_OFF)
    off = (await sinopac_switch(switch), await sinopac_switch(other_process))

    write_by_hand(ordering_project, f"  {ORDERING_OFF}\n", "")
    unset = await sinopac_switch(switch)

    write_by_hand(ordering_project, "temperature: 0.7", f"temperature: 99\n  {ORDERING_ON}")
    not_loadable = await sinopac_switch(switch)

    shown, nobody = (FeatureVisibility.ADMINISTRATORS, ShioajiServer.SIMULATION), (FeatureVisibility.OFF, ShioajiServer.SIMULATION)
    assert on == (shown, shown)
    assert off == (nobody, nobody)
    assert (unset, not_loadable) == (None, None), "files that leave the switch out, or no start accepts, let nobody order"


async def test_a_saved_log_level_and_the_follow_times_apply_at_once_and_the_times_read_in_the_day_s_order(project: Path) -> None:
    original, harness = text_of(project), admin_harness(project)

    async with app_of(harness) as app, client_at(app) as client:
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        saved = await save(client, ("behavior.log_level", "WARNING"), ("ranking.follow_times", ["10:30:00", "09:15:00"]))

        with app.state.runtime_switch.hold() as current:
            offered = current.runtime.config.ranking.follow_times

    assert "follow_times" not in original and values_of(saved)["behavior.log_level"] == "WARNING"
    assert harness.logger.level == "WARNING" and "log_level: WARNING" in text_of(project)
    assert [f"{offer:%H:%M}" for offer in offered] == ["09:15", "10:30"]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("behavior.log_level", "LOUD"),
        ("ranking.follow_times", []),
        ("ranking.follow_times", ["08:59:00", "09:30:00"]),
        ("ranking.follow_times", ["13:25:00"]),
        ("api.follow_schedule_poll_seconds", 1),
        ("api.world_interval_minutes", 1),
        ("stock_page.system_writing.daily_ai_calls", 10_001),
    ],
    ids=[
        "log-level",
        "no-follow-time",
        "follow-time-before-continuous-trading",
        "follow-time-in-the-closing-auction",
        "poll-too-often",
        "world-too-often",
        "ai-calls",
    ],
)
async def test_a_newly_shown_setting_out_of_its_range_is_refused_at_its_setting(project: Path, path: str, value: Any) -> None:
    original = text_of(project)

    async with serve(admin_harness(project)) as client:
        response = await save(client, (path, value))

    problems = response.json()["problems"]
    assert (response.status_code, response.json()["code"]) == (422, "settings_refused")
    assert problems and all(problem["path"] == path or problem["path"].startswith(f"{path}.") for problem in problems)
    assert text_of(project) == original
