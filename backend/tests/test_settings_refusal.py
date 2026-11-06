"""
Settings that do not validate stop the CLI and the Web API with each problem's location and message. pydantic's own
text shows the input, which can begin with a credential from .env, so the refusal never carries a value.
"""

import asyncio
import os
import re
import sys
import traceback
from pathlib import Path

import pytest
import yaml
from trading_stack import SilentLogger

from a_domain.ports.system.settings_files import SettingsProblem
from a_domain.types.enums import Audience, SettingsFile, SystemEnvironment
from b_application.config.settings_loader import InvalidSettingsError, load_settings, startup_settings
from c_infrastructure.system.settings_files import SettingsFiles

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
CONFIG = ROOT / "config"

SECRET = "Kq7x9"
"""Short enough that pydantic's shortened input value shows all of it."""

CREDENTIALS = {"DB_USER": SECRET, "DB_PASSWORD": SECRET, "DB_HOST": "db.example", "DB_NAME": "stock_agent"}
"""Every PostgreSQL credential set while db.backend is sqlite, which the database selection refuses."""

SERVE = "import uvicorn, main; uvicorn.run(main.app, host='127.0.0.1', port=0)"


def without_connection_timeout() -> str:
    text = (CONFIG / "appsetting.yaml").read_text(encoding="utf-8")
    return re.sub(r"\n  connection_timeout: .*", "", text, count=1)


def away_from_the_repository_env(folder: Path) -> Path:
    """A working folder with config/ and no .env above it, so only the test's fake credentials are read."""
    (folder / "config").symlink_to(CONFIG)
    return folder


@pytest.mark.parametrize(
    ("environment", "appsetting", "location", "words"),
    [
        pytest.param(CREDENTIALS, None, "db", "Choose the database with db.backend", id="database-selection"),
        pytest.param(
            {"OPENAI_API_KEY": SECRET},
            without_connection_timeout(),
            "ai.connection_timeout",
            "Field required",
            id="missing-ai-setting",
        ),
    ],
)
def test_settings_that_do_not_validate_name_each_problem_and_never_a_value_from_the_environment(
    environment: dict[str, str], appsetting: str | None, location: str, words: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(away_from_the_repository_env(tmp_path))
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(InvalidSettingsError) as refused:
        load_settings(tmp_path, {SettingsFile.APPSETTING: appsetting} if appsetting else None)

    assert f"{location}: " in str(refused.value) and words in str(refused.value)
    assert SECRET not in "".join(traceback.format_exception(refused.value))


def test_a_candidate_is_validated_by_itself_not_by_the_file_on_disk() -> None:
    shipped = (CONFIG / "appsetting.yaml").read_text(encoding="utf-8")
    candidate = "".join(line for line in shipped.splitlines(keepends=True) if "mis_quotes_url:" not in line)

    with pytest.raises(InvalidSettingsError) as refused:
        load_settings(ROOT, {SettingsFile.APPSETTING: candidate})

    assert "sources.exchange.mis_quotes_url: Field required" in str(refused.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("command", [["-m", "d_presentation.cli.interactive"], ["-c", SERVE]], ids=["cli", "served-api"])
async def test_the_cli_and_the_served_api_print_invalid_settings_alone_and_exit_1(command: list[str], tmp_path: Path) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        *command,
        cwd=away_from_the_repository_env(tmp_path),
        env={"PYTHONPATH": os.pathsep.join([str(BACKEND / "src"), str(BACKEND)]), "PATH": "/usr/bin:/bin", **CREDENTIALS},
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
    printed = (stdout + stderr).decode()

    assert process.returncode == 1
    assert "db.backend is sqlite" in printed
    assert "Traceback" not in printed and SECRET not in printed


SHIPPED = {file: (CONFIG / file.file_name).read_text(encoding="utf-8") for file in SettingsFile}


def at(text: str, needle: str) -> tuple[int, int]:
    """The 1-based line and column where `needle` starts in `text`."""
    before = text[: text.index(needle)]
    return before.count("\n") + 1, len(before) - (before.rfind("\n") + 1) + 1


def refused(file: SettingsFile, text: str) -> list[SettingsProblem]:
    with pytest.raises(InvalidSettingsError) as error:
        load_settings(ROOT, {file: text})

    return error.value.problems


def test_the_shipped_settings_load_and_name_no_unread_key() -> None:
    assert load_settings(ROOT).environment.value == "dev"


def test_every_yaml_file_in_config_is_a_settings_file() -> None:
    assert {file.file_name for file in SettingsFile} == {path.name for path in CONFIG.glob("*.yaml")}


def test_a_file_that_does_not_parse_is_refused_at_the_parsers_mark() -> None:
    text = SHIPPED[SettingsFile.APPSETTING].replace("  order_mode: mock_only\n", "  order_mode: [mock_only\n", 1)

    [problem] = refused(SettingsFile.APPSETTING, text)

    assert (problem.file, problem.message.startswith("YAML: ")) == (SettingsFile.APPSETTING, True)
    assert problem.line is not None and problem.line > at(text, "  order_mode: [mock_only")[0]


def test_a_refused_value_is_located_at_its_key() -> None:
    text = SHIPPED[SettingsFile.APPSETTING].replace("  order_mode: mock_only", "  order_mode: sometimes", 1)

    [problem] = refused(SettingsFile.APPSETTING, text)

    assert (problem.file, problem.path, problem.line, problem.column) == (
        SettingsFile.APPSETTING,
        "trading.order_mode",
        *at(text, "order_mode: sometimes"),
    )
    assert "sometimes" not in problem.message
    assert str(problem).startswith(f"appsetting.yaml line {problem.line}, column 3, trading.order_mode: Input should be")


@pytest.mark.parametrize(
    ("addition", "path", "words"),
    [
        ("  order_mod: live\n", "trading.order_mod", "names no setting"),
        ("  OPENAI_API_KEY: from-yaml\n", None, "comes from the environment"),
        ("  password: from-yaml\n", None, "comes from the environment"),
        ("  system_prompt: from-yaml\n", None, "is the prompt system_prompt of instructions.yaml"),
    ],
    ids=["unknown", "environment-alias", "environment-field", "prompt"],
)
def test_a_key_the_app_would_not_read_is_refused_at_its_line(addition: str, path: str | None, words: str) -> None:
    section = {"order_mod": "trading:\n", "OPENAI_API_KEY": "ai:\n", "password": "db:\n", "system_prompt": "ai:\n"}
    key = addition.strip().split(":")[0]
    text = SHIPPED[SettingsFile.APPSETTING].replace(section[key], section[key] + addition, 1)

    [problem] = refused(SettingsFile.APPSETTING, text)

    assert (problem.line, problem.column) == at(text, addition.lstrip())
    assert problem.path == (path or f"{section[key].strip(':\n')}.{key}") and words in problem.message
    assert "from-yaml" not in str(problem)


def test_a_secret_can_never_be_written_into_appsetting_yaml_even_as_the_accounts_key() -> None:
    text = SHIPPED[SettingsFile.APPSETTING].replace("accounts:\n", "accounts:\n  ACCOUNTS_KEY: from-yaml\n  key: from-yaml\n", 1)

    problems = refused(SettingsFile.APPSETTING, text)

    assert [problem.path for problem in problems] == ["accounts.ACCOUNTS_KEY", "accounts.key"]


def test_instructions_yaml_takes_only_its_prompts_and_a_refused_prompt_is_located_there() -> None:
    unknown = SHIPPED[SettingsFile.INSTRUCTIONS] + "\nsystem_promt: typo\n"
    [typo] = refused(SettingsFile.INSTRUCTIONS, unknown)

    assert (typo.file, typo.path, typo.line) == (SettingsFile.INSTRUCTIONS, "system_promt", at(unknown, "system_promt")[0])

    prompts = yaml.safe_load(SHIPPED[SettingsFile.INSTRUCTIONS])
    without_placeholder = yaml.safe_dump({**prompts, "rag_injection_prompt": "no results placeholder here"}, allow_unicode=True)
    [prompt] = refused(SettingsFile.INSTRUCTIONS, without_placeholder)

    assert (prompt.file, prompt.path) == (SettingsFile.INSTRUCTIONS, "ai.rag_injection_prompt")
    assert (prompt.line, prompt.column) == at(without_placeholder, "rag_injection_prompt:")


def test_an_unsafe_trading_setup_is_located_at_the_setting_it_names(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    for file, text in SHIPPED.items():
        (tmp_path / "config" / file.file_name).write_text(text, encoding="utf-8")
    (tmp_path / "config" / "strategies").symlink_to(CONFIG / "strategies")
    text = SHIPPED[SettingsFile.APPSETTING].replace("  execution_provider: mock", "  execution_provider: shioaji", 1)
    files = SettingsFiles(project_root=tmp_path, max_bytes=262_144, backups_kept=3, logger=SilentLogger())

    problems = files.check(SettingsFile.APPSETTING, text, SystemEnvironment.DEV, Audience.PERSONAL, "127.0.0.1")
    [problem] = [problem for problem in problems if problem.path != "ai.active_model"]

    assert (problem.path, problem.line) == ("trading.execution_provider", at(text, "execution_provider: shioaji")[0])
    assert problem.message == "environment dev trades only on mock, not shioaji"


def test_a_missing_ai_key_is_a_located_refusal_at_the_first_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = away_from_the_repository_env(tmp_path)
    monkeypatch.chdir(project)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    text = (CONFIG / "appsetting.yaml").read_text(encoding="utf-8")

    with pytest.raises(InvalidSettingsError) as refused:
        startup_settings(project)

    [problem] = refused.value.problems
    assert (problem.file, problem.path, problem.line) == (SettingsFile.APPSETTING, "ai.active_model", at(text, "active_model:")[0])
    assert problem.message == "claude needs ANTHROPIC_API_KEY in the environment or .env; the app would not start"


@pytest.mark.parametrize(
    ("offered", "gemini_model", "keys", "message"),
    [
        pytest.param(
            "[gemini, openai]",
            "\n    gemini: gemini-2.5-flash",
            {"GEMINI_API_KEY": "placeholder"},
            "openai needs OPENAI_API_KEY in the environment or .env; the app would not start",
            id="no-key",
        ),
        pytest.param(
            "[openai, gemini]",
            "",
            {"OPENAI_API_KEY": "placeholder", "GEMINI_API_KEY": "placeholder"},
            "gemini needs its model id under ai.available_models.gemini; the app would not start",
            id="no-model-id",
        ),
    ],
)
def test_a_model_offered_to_users_without_its_key_or_model_id_is_a_located_refusal(
    offered: str, gemini_model: str, keys: dict[str, str], message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = away_from_the_repository_env(tmp_path)
    monkeypatch.chdir(project)
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {"ANTHROPIC_API_KEY": "placeholder", **keys}.items():
        monkeypatch.setenv(name, value)
    shipped = (CONFIG / "appsetting.yaml").read_text(encoding="utf-8")
    text = shipped.replace("  user_selectable: []", f"  user_selectable: {offered}", 1)
    text = text.replace("\n    gemini: gemini-2.5-flash", gemini_model, 1)

    with pytest.raises(InvalidSettingsError) as refused:
        startup_settings(project, {SettingsFile.APPSETTING: text})

    [problem] = refused.value.problems
    line = at(text, f"user_selectable: {offered}")[0]
    assert (problem.file, problem.path, problem.line) == (SettingsFile.APPSETTING, "ai.user_selectable.1", line)
    assert problem.message == message


def project_with_shipped_settings(folder: Path) -> Path:
    """A project folder whose config/ holds a copy of the shipped settings files and the built-in strategies."""
    (folder / "config").mkdir()
    for file, text in SHIPPED.items():
        (folder / "config" / file.file_name).write_text(text, encoding="utf-8")
    (folder / "config" / "strategies").symlink_to(CONFIG / "strategies")
    return folder


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("environment: dev", "environment: test", "this process started as dev: the environment changes only when the app restarts"),
        (
            "audience: personal",
            "audience: public",
            "this process started as personal: the audience changes only when the app restarts",
        ),
    ],
    ids=["environment", "audience"],
)
def test_settings_of_another_environment_or_audience_than_the_process_started_in_are_refused_where_they_set_it(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    text = SHIPPED[SettingsFile.APPSETTING].replace(old, new, 1)

    with pytest.raises(InvalidSettingsError) as refused:
        startup_settings(
            project_with_shipped_settings(tmp_path), {SettingsFile.APPSETTING: text}, SystemEnvironment.DEV, Audience.PERSONAL
        )

    [problem] = refused.value.problems
    assert (problem.file, problem.path, problem.line, problem.column) == (SettingsFile.APPSETTING, old.split(":")[0], *at(text, new))
    assert problem.message.endswith(message)


@pytest.mark.parametrize("flag", ["enable_web_search", "enable_x_search"])
def test_a_public_site_whose_ai_would_search_the_web_or_x_is_refused_where_the_search_is_turned_on(tmp_path: Path, flag: str) -> None:
    text = SHIPPED[SettingsFile.APPSETTING].replace("audience: personal", "audience: public", 1)
    text = text.replace(f"  {flag}: false", f"  {flag}: true", 1)

    with pytest.raises(InvalidSettingsError) as refused:
        startup_settings(
            project_with_shipped_settings(tmp_path), {SettingsFile.APPSETTING: text}, SystemEnvironment.DEV, Audience.PUBLIC
        )

    [problem] = refused.value.problems
    assert (problem.file, problem.path, problem.line, problem.column) == (SettingsFile.APPSETTING, f"behavior.{flag}", *at(text, flag))
    assert problem.message.startswith("must be false on audience public")


def test_a_personal_site_may_search_the_web_and_x(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    text = SHIPPED[SettingsFile.APPSETTING]
    text = text.replace("  enable_web_search: false", "  enable_web_search: true", 1).replace(
        "  enable_x_search: false", "  enable_x_search: true", 1
    )

    config = startup_settings(
        project_with_shipped_settings(tmp_path), {SettingsFile.APPSETTING: text}, SystemEnvironment.DEV, Audience.PERSONAL
    )

    assert (config.audience, config.behavior.enable_web_search, config.behavior.enable_x_search) == (Audience.PERSONAL, True, True)
