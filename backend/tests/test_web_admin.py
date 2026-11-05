"""The administrator's settings editor over HTTP, on a temporary copy of config/: never the repository's files."""

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest
import support.harness
import yaml
from sqlalchemy import make_url
from support.databases import POSTGRES_URL, empty_database
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
from support.settings import environment_setup
from support.web import app_of, client_at, ended, hold_stock_list, serve, sign_in

from a_domain.types.enums import DatabaseBackend, ExecutionProvider, OrderMode, SettingsFile, SystemEnvironment
from b_application.config.api_config import ApiConfig
from b_application.config.app_config import AppConfig
from d_presentation.dependencies import Runtime
from d_presentation.live_runtime import open_runtime_switch
from d_presentation.web.app import create_app

pytestmark = pytest.mark.asyncio

REPOSITORY_CONFIG = Path(__file__).resolve().parents[2] / "config"
APPSETTING = "/v1/admin/settings/appsetting"


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


def admin_harness(project: Path):
    return build_harness(settings_root=project)


def text_of(project: Path, file: SettingsFile = SettingsFile.APPSETTING) -> str:
    return (project / "config" / file.file_name).read_text(encoding="utf-8")


def write_by_hand(project: Path, old: str, new: str) -> None:
    assert old in text_of(project)
    (project / "config" / "appsetting.yaml").write_text(text_of(project).replace(old, new, 1), encoding="utf-8")


def at(text: str, needle: str) -> tuple[int, int]:
    before = text[: text.index(needle)]
    return before.count("\n") + 1, len(before) - (before.rfind("\n") + 1) + 1


async def read(client, file: str = "appsetting") -> tuple[str, str]:
    """The file's text and revision, as the editor page reads them."""
    document = (await client.get(f"/v1/admin/settings/{file}")).json()
    return document["text"], document["status"]["revision"]


async def save(client, revision: str, text: str, file: str = "appsetting", password: str | None = ADMINISTRATOR_PASSWORD):
    """A save as the editor page sends it, with the administrator's password unless the test leaves it out (None)."""
    body = {"confirm": True, "revision": revision, "text": text, "password": password}
    return await client.put(f"/v1/admin/settings/{file}", json=body)


async def test_only_an_administrator_opens_the_settings_files_and_a_user_stays_signed_in(project: Path) -> None:
    harness = admin_harness(project)
    harness.users.add(MEMBER, MEMBER_PASSWORD)

    async with serve(harness, authorized=False) as signed_out:
        anonymous = await signed_out.get(APPSETTING)

    async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as member:
        refused = await member.get(APPSETTING)
        still_signed_in = await member.get("/v1/watchlist")

    async with serve(harness) as administrator:
        opened = await administrator.get(APPSETTING)

    assert (anonymous.status_code, refused.status_code, still_signed_in.status_code, opened.status_code) == (401, 403, 200, 200)


async def test_every_settings_file_is_read_whole_with_the_revision_the_server_runs_and_the_environment_read_only(
    project: Path,
) -> None:
    async with serve(admin_harness(project)) as client:
        overview = (await client.get("/v1/admin/settings")).json()
        document = (await client.get(APPSETTING)).json()
        unknown = await client.get("/v1/admin/settings/..%2F.env")

    assert overview["environment"] == "dev"
    assert [status["file_name"] for status in overview["files"]] == ["appsetting.yaml", "instructions.yaml"]
    assert all(status["revision"] == status["running_revision"] for status in overview["files"])
    assert document["text"] == text_of(project) and unknown.status_code in {404, 422}


async def test_a_preview_writes_nothing_and_a_save_writes_the_text_byte_for_byte_backs_up_and_audits_without_values(
    project: Path,
) -> None:
    async with serve(admin_harness(project)) as client:
        original, revision = await read(client)
        edited = original.replace("temperature: 0.7", "temperature: 0.3").replace("# config/appsetting.yaml", "# edited on the Web")
        preview = (await client.post(f"{APPSETTING}/preview", json={"revision": revision, "text": edited})).json()
        assert text_of(project) == original
        saved = await save(client, revision, edited)
        backups = (await client.get(f"{APPSETTING}/backups")).json()
        audit = (await client.get("/v1/admin/audit")).json()

    assert preview["problems"] == [] and preview["changed"] == ["ai.temperature"]
    assert any(line.startswith("+  temperature: 0.3") for line in preview["diff"]) and preview["saved"] is False
    assert saved.status_code == 200 and saved.json()["saved"] and saved.json()["applied"] and text_of(project) == edited
    assert [backup["revision"] for backup in backups] == [revision]
    for folder in (".settings-admin", ".settings-admin/backups", ".settings-admin/backups/appsetting"):
        assert (project / folder).stat().st_mode & 0o077 == 0, folder
    assert (audit[0]["settings"], audit[0]["actor"], audit[0]["actor_name"]) == (["ai.temperature"], "local", ADMINISTRATOR.username)
    kept = (project / ".settings-admin" / "audit.jsonl").read_text(encoding="utf-8")
    assert "0.3" not in kept and ADMINISTRATOR.username not in kept and json.loads(kept)["actor"] == "local"


async def test_a_stale_revision_is_refused_and_changes_nothing(project: Path) -> None:
    async with serve(admin_harness(project)) as client:
        original, revision = await read(client)
        write_by_hand(project, "# config/appsetting.yaml", "# edited elsewhere")
        edited = text_of(project)
        response = await save(client, revision, original.replace("temperature: 0.7", "temperature: 0.2"))

    assert response.status_code == 409 and text_of(project) == edited


@pytest.mark.parametrize(
    ("file", "old", "new", "path", "needle"),
    [
        ("appsetting", "  order_mode: mock_only", "  order_mode: [mock_only", None, None),
        ("appsetting", "  order_mode: mock_only", "  order_mode: sometimes", "trading.order_mode", "order_mode: sometimes"),
        ("appsetting", "trading:\n", "trading:\n  order_mod: live\n", "trading.order_mod", "order_mod: live"),
        ("appsetting", "ai:\n", "ai:\n  OPENAI_API_KEY: sk-from-the-web\n", "ai.OPENAI_API_KEY", "OPENAI_API_KEY"),
        ("appsetting", "temperature: 0.7", "temperature: 5", "ai.temperature", "temperature: 5"),
        ("instructions", "rag_injection_prompt:", "rag_prompt_typo:", "rag_prompt_typo", "rag_prompt_typo"),
    ],
    ids=["does-not-parse", "refused-value", "unknown-key", "secret-key", "out-of-range", "unknown-prompt"],
)
async def test_a_file_the_app_would_refuse_is_never_saved_and_each_problem_says_where(
    project: Path, file: str, old: str, new: str, path: str | None, needle: str | None
) -> None:
    async with serve(admin_harness(project)) as client:
        original, revision = await read(client, file)
        text = original.replace(old, new, 1)
        response = await save(client, revision, text, file)

    problems = response.json()["problems"]
    assert response.status_code == 422 and problems and all(problem["line"] for problem in problems)
    if needle is not None:
        assert (problems[0]["path"], problems[0]["line"], problems[0]["column"]) == (path, *at(text, needle))
    assert text_of(project, SettingsFile(file)) == original and not (project / ".settings-admin").exists()
    assert "sk-from-the-web" not in response.text


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
        ("trading:\n  order_mode: [mock_only\n", None, 3, 1),
    ],
    ids=["alias-bomb", "does-not-parse"],
)
async def test_a_preview_of_a_text_that_does_not_parse_names_no_setting_and_says_where_it_stops(
    project: Path, text: str, message: str | None, line: int, column: int
) -> None:
    async with serve(admin_harness(project)) as client:
        _, revision = await read(client)
        preview = (await client.post(f"{APPSETTING}/preview", json={"revision": revision, "text": text})).json()

    [problem] = preview["problems"]
    assert preview["changed"] == [] and (problem["file"], problem["line"], problem["column"]) == ("appsetting", line, column)
    assert message is None or problem["message"] == message


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
        original, revision = await read(client)
        old = "built_in_strategies: [conservative, balanced, aggressive]"
        text = original.replace(old, f"built_in_strategies: [conservative, balanced, aggressive, {strategy_id}]", 1)
        response = await client.post(f"{APPSETTING}/preview", json={"revision": revision, "text": text})

    [problem] = response.json()["problems"]
    assert old in original and (problem["path"], problem["message"]) == ("technical.built_in_strategies.3", message)
    assert str(project) not in response.text and "Errno" not in response.text


async def test_a_save_that_changes_the_environment_is_refused_until_a_restart(project: Path) -> None:
    async with serve(admin_harness(project)) as client:
        original, revision = await read(client)
        text = original.replace("environment: dev", "environment: test", 1)
        preview = (await client.post(f"{APPSETTING}/preview", json={"revision": revision, "text": text})).json()
        response = await save(client, revision, text)

    [problem] = response.json()["problems"]
    assert response.status_code == 422 and preview["problems"] == response.json()["problems"]
    assert (problem["path"], problem["line"], problem["column"]) == ("environment", *at(text, "environment: test"))
    assert "the environment changes only when the app restarts" in problem["message"] and text_of(project) == original


async def test_every_save_needs_the_password_in_the_same_request_and_a_wrong_one_keeps_the_session(project: Path) -> None:
    async with serve(admin_harness(project)) as client:
        original, revision = await read(client)
        text = original.replace("temperature: 0.7", "temperature: 0.6")
        without = await save(client, revision, text, password=None)
        wrong = await save(client, revision, text, password="not the password")
        still_signed_in = await client.get("/v1/auth/me")
        unchanged = text_of(project)
        right = await save(client, revision, text)

    assert (without.status_code, wrong.status_code, still_signed_in.status_code) == (403, 403, 200)
    assert without.json()["detail"] == "Re-enter your password to save the settings. Nothing was saved."
    assert unchanged == original and right.status_code == 200 and text_of(project) == text


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('nvidia_base_url: "https://integrate.api.nvidia.com/v1"', 'nvidia_base_url: "https://attacker.example/v1"'),
        ('push_url: "https://api.line.me/v2/bot/message/push"', 'push_url: "https://attacker.example/push"'),
        ("board_lot_shares: 1000", "board_lot_shares: 1"),
        ("settings_password_failures: 5", "settings_password_failures: 1000"),
        ("sign_in_window_minutes: 15", "sign_in_window_minutes: 1"),
        ("order_mode: mock_only", "order_mode: disabled"),
    ],
    ids=["ai-base-url", "line-push-url", "board-lot", "password-limit", "sign-in-window", "order-mode"],
)
async def test_a_stolen_session_alone_changes_no_setting(project: Path, old: str, new: str) -> None:
    async with serve(admin_harness(project)) as client:
        original, revision = await read(client)
        response = await save(client, revision, original.replace(old, new, 1), password=None)
        document = (await client.get(APPSETTING)).json()

    assert old in original and response.status_code == 403
    assert text_of(project) == original and document["status"]["running_revision"] == revision


@pytest.mark.parametrize(
    ("section", "path"),
    [
        ("api:\n  allowed_hosts: [admin.example]\n", "api.allowed_hosts"),
        ("api:\n  settings_file_max_bytes: 1000\n", "api.settings_file_max_bytes"),
    ],
    ids=["host-left-out", "files-too-large"],
)
async def test_a_save_that_would_lock_the_administrator_out_of_the_editor_is_refused_at_that_setting(
    project: Path, section: str, path: str
) -> None:
    async with serve(admin_harness(project)) as client:
        original, revision = await read(client)
        text = f"{original}{section}"
        preview = (await client.post(f"{APPSETTING}/preview", json={"revision": revision, "text": text})).json()
        response = await save(client, revision, text)
        after = await client.get(APPSETTING)

    [problem] = response.json()["problems"]
    assert response.status_code == 422 and preview["problems"] == response.json()["problems"]
    assert (problem["path"], problem["line"]) == (path, at(text, path.split(".")[1])[0])
    assert text_of(project) == original and after.status_code == 200


async def test_each_refusal_says_which_it_is_by_a_stable_code(project: Path) -> None:
    harness = admin_harness(project)
    harness.users.add(MEMBER, MEMBER_PASSWORD)

    async with serve(harness) as client:
        original, revision = await read(client)
        text = original.replace("temperature: 0.7", "temperature: 0.6")
        required = await save(client, revision, text, password=None)
        refused = await save(client, revision, text, password="not the password")
        problems = await save(client, revision, original.replace("order_mode: mock_only", "order_mode: sometimes"))
        invalid = await client.put(APPSETTING, json={"confirm": True})

    async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as member:
        not_an_administrator = await member.get(APPSETTING)

    answers = (required, refused, not_an_administrator, problems, invalid)
    assert [answer.status_code for answer in answers] == [403, 403, 403, 422, 422]
    assert [answer.json()["code"] for answer in answers] == [
        "password_required",
        "password_refused",
        "administrators_only",
        "settings_refused",
        "invalid_request",
    ]


async def test_wrong_passwords_have_their_own_limit_and_never_lock_the_sign_in(project: Path) -> None:
    harness = admin_harness(project)
    limit = harness.config.accounts.settings_password_failures

    async with serve(harness) as client:
        original, revision = await read(client)
        text = original.replace("order_mode: mock_only", "order_mode: disabled")
        wrong = [(await save(client, revision, text, password="guess")).status_code for _ in range(limit + 1)]
        throttled = await save(client, revision, text, password=ADMINISTRATOR_PASSWORD)
        signed_in = await client.post(
            "/v1/auth/sign-in", json={"identifier": ADMINISTRATOR.username, "password": ADMINISTRATOR_PASSWORD}
        )

    assert wrong == [403] * limit + [429] and throttled.status_code == 429 and "Retry-After" in throttled.headers
    assert signed_in.status_code == 200 and text_of(project) == original


async def test_a_restore_goes_through_the_same_checks_and_puts_the_whole_old_text_back(project: Path) -> None:
    async with serve(admin_harness(project)) as client:
        original, first = await read(client)
        changed = original.replace("temperature: 0.7", "temperature: 0.4").replace("# config/appsetting.yaml", "# saved")
        assert (await save(client, first, changed)).status_code == 200
        _, current = await read(client)
        [backup] = (await client.get(f"{APPSETTING}/backups")).json()
        route = f"{APPSETTING}/backups/{backup['backup_id']}"
        preview = (await client.post(f"{route}/preview", json={"revision": current})).json()
        confirmed = {"confirm": True, "password": ADMINISTRATOR_PASSWORD}
        stale = await client.post(f"{route}/restore", json={**confirmed, "revision": first})
        unconfirmed = await client.post(f"{route}/restore", json={"confirm": True, "revision": current})
        kept = text_of(project)
        restored = await client.post(f"{route}/restore", json={**confirmed, "revision": current})
        audit = (await client.get("/v1/admin/audit")).json()

    assert preview["changed"] == ["ai.temperature"] and preview["problems"] == []
    assert (stale.status_code, unconfirmed.status_code, restored.status_code) == (409, 403, 200) and kept == changed
    assert text_of(project) == original and [entry["action"] for entry in audit] == ["restore", "save"]


async def test_a_symlinked_settings_file_is_never_read_or_written(project: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    outside = tmp_path_factory.mktemp("outside") / "appsetting.yaml"
    outside.write_text(text_of(project), encoding="utf-8")
    (project / "config" / "appsetting.yaml").unlink()
    os.symlink(outside, project / "config" / "appsetting.yaml")

    async with serve(admin_harness(project)) as client:
        response = await client.get(APPSETTING)
        saved = await save(client, "0" * 64, "environment: dev\n")

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
        response = await client.get(APPSETTING)

    assert (response.status_code, response.json()["detail"]) == (code, detail)


async def test_a_text_too_large_for_the_editor_is_refused_not_failed(project: Path) -> None:
    async with serve(admin_harness(project)) as client:
        text, revision = await read(client, "instructions")
        prompts = yaml.safe_load(text)
        response = await save(client, revision, yaml.safe_dump({**prompts, "system_prompt": "x" * 300_000}), "instructions")

    [problem] = response.json()["problems"]
    assert response.status_code == 422 and problem["path"] == "api.settings_file_max_bytes"
    assert "is smaller than instructions.yaml" in problem["message"]


async def test_a_save_during_a_running_run_applies_at_once_and_the_run_finishes_on_the_runtime_it_started_on(project: Path) -> None:
    harness = admin_harness(project)
    release = hold_stock_list(harness)

    async with app_of(harness) as app, client_at(app) as client:
        switch = app.state.runtime_switch
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        run = (await client.post("/v1/runs/full-cycle", json={"confirm": True})).json()["run_id"]
        text, revision = await read(client)
        saved = (await save(client, revision, text.replace("temperature: 0.7", "temperature: 0.2"))).json()

        with switch.hold() as current:
            temperature = current.runtime.config.ai.temperature

        held_by_the_run = switch.status.draining
        release.set()
        finished = await ended(client, run)

        for _ in range(1000):
            if switch.status.draining == 0:
                break
            await asyncio.sleep(0)

        assert (saved["saved"], saved["applied"], temperature, held_by_the_run) == (True, True, 0.2, 1)
        assert finished["state"] == "finished" and switch.status.draining == 0


async def test_a_save_of_the_run_cap_applies_to_the_next_run_started(project: Path) -> None:
    harness = admin_harness(project)
    harness.users.add(MEMBER, MEMBER_PASSWORD)
    release = hold_stock_list(harness)

    async with app_of(harness) as app, client_at(app) as administrator, client_at(app, "127.0.0.2") as member:
        assert (await sign_in(administrator, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        assert (await sign_in(member, MEMBER.username, MEMBER_PASSWORD)).status_code == 200
        text, revision = await read(administrator)
        saved = await save(administrator, revision, text.replace("max_concurrent_runs: 2", "max_concurrent_runs: 1"))
        running = await administrator.post("/v1/runs/full-cycle", json={"confirm": True})
        refused = await member.post("/v1/runs/full-cycle", json={"confirm": True})
        release.set()
        await ended(administrator, running.json()["run_id"])

    assert (saved.status_code, saved.json()["applied"], running.status_code, refused.status_code) == (200, True, 202, 429)


async def test_a_save_of_the_log_level_applies_at_once(project: Path) -> None:
    harness = admin_harness(project)

    async with serve(harness) as client:
        text, revision = await read(client)
        saved = await save(client, revision, text.replace("log_level: DEBUG", "log_level: WARNING"))

    assert (saved.status_code, saved.json()["applied"], harness.logger.level) == (200, True, "WARNING")


async def test_a_save_whose_audit_entry_cannot_be_written_changes_neither_the_file_nor_the_running_app(project: Path) -> None:
    (project / ".settings-admin" / "audit.jsonl").mkdir(parents=True)

    async with serve(admin_harness(project)) as client:
        original, revision = await read(client)

        with pytest.raises(IsADirectoryError):
            await save(client, revision, original.replace("temperature: 0.7", "temperature: 0.2"))

        document = (await client.get(APPSETTING)).json()

    assert text_of(project) == original and document["status"]["running_revision"] == revision


async def test_two_saves_from_one_revision_apply_once_and_the_other_is_told_to_read_again(project: Path) -> None:
    async with serve(admin_harness(project)) as client:
        text, revision = await read(client)
        answers = await asyncio.gather(
            save(client, revision, text.replace("temperature: 0.7", "temperature: 0.2")),
            save(client, revision, text.replace("temperature: 0.7", "temperature: 0.3")),
        )

    assert sorted(answer.status_code for answer in answers) == [200, 409]
    assert len(list((project / ".settings-admin" / "backups" / "appsetting").iterdir())) == 1


async def test_buzz_and_intraday_are_refused_once_the_administrator_switches_to_shioaji(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for credential in ("SHIOAJI_API_KEY_TEST", "SHIOAJI_SECRET_KEY_TEST"):
        monkeypatch.setenv(credential, "placeholder")
    write_by_hand(project, "environment: dev", "environment: test")
    config = environment_setup(harness_config(), SystemEnvironment.TEST, ExecutionProvider.MOCK, OrderMode.MOCK_ONLY)
    harness = build_harness(config=config, settings_root=project)
    release = hold_stock_list(harness)

    async with serve(harness) as client:
        before = await client.post("/v1/runs/buzz-scan", json={"confirm": True})
        text, revision = await read(client)
        shioaji = text.replace("execution_provider: mock", "execution_provider: shioaji").replace(
            "order_mode: mock_only", "order_mode: disabled"
        )
        saved = await save(client, revision, shioaji)
        refused = [(await client.post(f"/v1/runs/{route}", json={"confirm": True})).status_code for route in ("buzz-scan", "intraday")]
        release.set()
        run = await ended(client, before.json()["run_id"])

    assert (before.status_code, saved.status_code, saved.json()["changed"]) == (
        202,
        200,
        ["trading.execution_provider", "trading.order_mode"],
    )
    assert refused == [403, 403] and run["state"] == "finished"


@pytest.fixture
def real_project(project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The project copy served by the real opener: SQLite and Chroma inside it, no .env."""
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
        text, revision = await read(client)
        for name, value in {
            "DB_USER": "owner",
            "DB_PASSWORD": "Kq7x9-secret",
            "DB_HOST": "127.0.0.1",
            "DB_PORT": "9",
            "DB_NAME": "absent",
        }.items():
            monkeypatch.setenv(name, value)
        response = await save(client, revision, text.replace("backend: sqlite", "backend: postgresql"))
        after = await client.get("/v1/auth/me")

    [problem] = response.json()["problems"]
    assert response.status_code == 422 and problem["message"].startswith("The app would not start: ")
    assert "Kq7x9" not in response.text and "127.0.0.1" not in response.text and after.status_code == 200
    assert text_of(real_project) == text and not (real_project / ".settings-admin").exists()


@pytest.mark.skipif(POSTGRES_URL is None, reason="STOCK_AGENT_TEST_POSTGRES_URL is not set")
async def test_a_database_with_no_account_of_the_saving_administrator_is_refused(
    real_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(lambda: open_runtime_switch(real_project))
    await empty_database(DatabaseBackend.POSTGRESQL, real_project)

    async with app.router.lifespan_context(app), client_at(app) as client:
        await set_up_and_sign_in(app, client)
        text, revision = await read(client)
        url = make_url(str(POSTGRES_URL))
        credentials = {"DB_USER": url.username, "DB_PASSWORD": url.password or "trial", "DB_HOST": url.host, "DB_NAME": url.database}
        for name, value in {**credentials, "DB_PORT": str(url.port or 5432)}.items():
            monkeypatch.setenv(name, str(value))
        response = await save(client, revision, text.replace("backend: sqlite", "backend: postgresql"))

    assert response.status_code == 422 and text_of(real_project) == text
    assert "no active administrator account of yours" in response.json()["problems"][0]["message"]


async def test_an_edit_on_disk_is_picked_up_by_the_watcher_and_runs_without_a_restart(project: Path) -> None:
    config = harness_config().model_copy(update={"api": ApiConfig(settings_poll_seconds=0.05)})
    harness = build_harness(config=config, settings_root=project)

    async with app_of(harness) as app, client_at(app) as client:
        assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200
        write_by_hand(project, "temperature: 0.7", "temperature: 0.2")
        _, disk = await read(client)

        for _ in range(200):
            if (await client.get(APPSETTING)).json()["status"]["running_revision"] == disk:
                break
            await asyncio.sleep(0.02)

        with app.state.runtime_switch.hold() as current:
            assert current.runtime.config.ai.temperature == 0.2


async def test_a_refused_edit_on_disk_is_reported_at_its_line_and_the_old_settings_keep_serving(project: Path) -> None:
    async with serve(admin_harness(project)) as client:
        _, running = await read(client)
        write_by_hand(project, "  order_mode: mock_only", "  order_mode: sometimes")
        refused = (await client.post("/v1/admin/settings/reload", json={"confirm": True})).json()
        still_serving = await client.get("/v1/watchlist")
        write_by_hand(project, "  order_mode: sometimes", "  order_mode: disabled")
        fixed = (await client.post("/v1/admin/settings/reload", json={"confirm": True})).json()

    [problem] = refused["refused"]["problems"]
    assert (problem["path"], problem["file"], problem["line"] is not None) == ("trading.order_mode", "appsetting", True)
    assert refused["files"][0]["running_revision"] == running == refused["refused"]["previous"]["appsetting"]
    assert still_serving.status_code == 200
    assert fixed["refused"] is None and fixed["files"][0]["running_revision"] == fixed["files"][0]["revision"] != running


async def test_the_reload_request_retries_an_unchanged_edit_once_the_database_is_back(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness, opened = admin_harness(project), runtime_for

    def database_down(harness: CliHarness, config: AppConfig) -> Runtime:
        raise ConnectionRefusedError("connect to the database failed")

    monkeypatch.setattr(support.harness, "runtime_for", database_down)

    async with serve(harness) as client:
        write_by_hand(project, "temperature: 0.7", "temperature: 0.2")
        _, disk = await read(client)
        down = (await client.post("/v1/admin/settings/reload", json={"confirm": True})).json()
        monkeypatch.setattr(support.harness, "runtime_for", opened)
        back = (await client.post("/v1/admin/settings/reload", json={"confirm": True})).json()

    [problem] = down["refused"]["problems"]
    assert problem["message"] == "The app would not start: ConnectionRefusedError. The server log has the details."
    assert down["files"][0]["running_revision"] != disk and down["refused"]["revisions"]["appsetting"] == disk
    assert back["refused"] is None and back["files"][0]["running_revision"] == disk
