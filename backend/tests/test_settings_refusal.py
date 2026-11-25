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
from support.settings import running_on

from a_domain.ports.system.settings_files import SettingsProblem
from a_domain.types.enums import Audience, SettingsFile, ShioajiServer, SystemEnvironment
from b_application.config.settings_loader import InvalidSettingsError, load_settings, production_notice, startup_settings

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
CONFIG = ROOT / "config"

SECRET = "Kq7x9"
"""Short enough that pydantic's shortened input value shows all of it."""

CREDENTIALS = {"DB_USER": SECRET, "DB_PASSWORD": SECRET, "DB_HOST": "db.example", "DB_NAME": "stock_agent", "DB_PORT": SECRET}
"""The database's settings with a port that is no number, which the settings refuse: pydantic's text would show it."""

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
        pytest.param(CREDENTIALS, None, "db.DB_PORT", "Input should be a valid integer", id="database-port"),
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


@pytest.mark.parametrize("variable", ["DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME"])
@pytest.mark.parametrize(("value", "words"), [(None, "Field required"), ("  ", "at least 1 character")], ids=["unset", "blank"])
def test_the_settings_refuse_to_load_while_one_of_the_databases_variables_is_unset_or_blank(
    variable: str, value: str | None, words: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(away_from_the_repository_env(tmp_path))
    monkeypatch.delenv("DB_PORT")
    complete = load_settings(tmp_path).db
    named = (os.environ["DB_USER"], os.environ["DB_HOST"], os.environ["DB_NAME"])

    if value is None:
        monkeypatch.delenv(variable)
    else:
        monkeypatch.setenv(variable, value)

    with pytest.raises(InvalidSettingsError) as refused:
        load_settings(tmp_path)

    [problem] = refused.value.problems
    assert problem.path == f"db.{variable}" and words in problem.message
    assert (complete.user, complete.host, complete.name, complete.port) == (*named, 5432)


def test_a_candidate_is_validated_by_itself_not_by_the_file_on_disk() -> None:
    shipped = (CONFIG / "appsetting.yaml").read_text(encoding="utf-8")
    candidate = "".join(line for line in shipped.splitlines(keepends=True) if "tpex_index_url:" not in line)

    with pytest.raises(InvalidSettingsError) as refused:
        load_settings(ROOT, {SettingsFile.APPSETTING: candidate})

    assert "sources.exchange.tpex_index_url: Field required" in str(refused.value)


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
    assert "db.DB_PORT: Input should be a valid" in printed
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
    text = SHIPPED[SettingsFile.APPSETTING].replace("  max_order_equity_pct: 0.25\n", "  max_order_equity_pct: [0.25\n", 1)

    [problem] = refused(SettingsFile.APPSETTING, text)

    assert (problem.file, problem.message.startswith("YAML: ")) == (SettingsFile.APPSETTING, True)
    assert problem.line is not None and problem.line > at(text, "  max_order_equity_pct: [0.25")[0]


def test_a_refused_value_is_located_at_its_key() -> None:
    text = SHIPPED[SettingsFile.APPSETTING].replace("  max_order_equity_pct: 0.25", "  max_order_equity_pct: plenty", 1)

    [problem] = refused(SettingsFile.APPSETTING, text)

    assert (problem.file, problem.path, problem.line, problem.column) == (
        SettingsFile.APPSETTING,
        "trading.max_order_equity_pct",
        *at(text, "max_order_equity_pct: plenty"),
    )
    assert "plenty" not in problem.message
    assert str(problem).startswith(f"appsetting.yaml line {problem.line}, column 3, trading.max_order_equity_pct: Input should be")


@pytest.mark.parametrize(
    ("line", "edited", "code", "params"),
    [
        (
            "  active_model: claude",
            "  active_model: sometimes",
            "enum",
            {"expected": "'openai', 'grok', 'gemini', 'groq', 'nvidia' or 'claude'"},
        ),
        ("  temperature: 0.7", "  temperature: 3", "less_than_equal", {"le": 2}),
        ("  temperature: 0.7", "  temperature: warm", "float_parsing", {}),
    ],
    ids=["choice", "bound", "type"],
)
def test_a_refusal_pydantic_words_names_its_type_and_the_schemas_limits_so_a_client_can_word_it(
    line: str, edited: str, code: str, params: dict[str, object]
) -> None:
    text = SHIPPED[SettingsFile.APPSETTING].replace(line, edited, 1)

    [problem] = refused(SettingsFile.APPSETTING, text)

    assert (problem.code, problem.params) == (code, params)
    assert all(value not in str(problem.params) for value in ("sometimes", "warm", "3"))


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
    sections = {"order_mod": "trading:\n", "OPENAI_API_KEY": "ai:\n", "password": "db:\n", "system_prompt": "ai:\n"}
    key = addition.strip().split(":")[0]
    section = sections[key]
    shipped = SHIPPED[SettingsFile.APPSETTING]
    text = shipped.replace(section, section + addition, 1) if section in shipped else f"{shipped}{section}{addition}"

    [problem] = refused(SettingsFile.APPSETTING, text)

    assert (problem.line, problem.column) == at(text, addition.lstrip())
    assert problem.path == (path or f"{section.strip(':\n')}.{key}") and words in problem.message
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
    text = SHIPPED[SettingsFile.APPSETTING].replace("environment: dev", "environment: prod", 1)

    with pytest.raises(InvalidSettingsError) as refused:
        startup_settings(tmp_path, {SettingsFile.APPSETTING: text}, running_on(SystemEnvironment.DEV), unsettled=0)

    [problem] = [problem for problem in refused.value.problems if problem.path == "environment"]

    assert (problem.path, problem.line) == ("environment", at(text, "environment: prod")[0])
    assert problem.message == (
        "environment is prod in the settings, but this process started as dev: the environment changes only when the app restarts"
    )


def test_a_missing_ai_key_is_a_located_refusal_at_the_first_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = away_from_the_repository_env(tmp_path)
    monkeypatch.chdir(project)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    text = (CONFIG / "appsetting.yaml").read_text(encoding="utf-8")

    with pytest.raises(InvalidSettingsError) as refused:
        startup_settings(project, unsettled=0)

    [problem] = refused.value.problems
    assert (problem.file, problem.path, problem.line) == (SettingsFile.APPSETTING, "ai.active_model", at(text, "active_model:")[0])
    assert problem.message == "claude needs ANTHROPIC_API_KEY in the environment or .env; the app would not start"


@pytest.mark.parametrize(
    ("offered", "gemini_model", "keys", "message", "code", "params"),
    [
        pytest.param(
            "[gemini, openai]",
            "\n    gemini: gemini-2.5-flash",
            {"GEMINI_API_KEY": "placeholder"},
            "openai needs OPENAI_API_KEY in the environment or .env; the app would not start",
            "ai_key_missing",
            {"provider": "openai", "variable": "OPENAI_API_KEY"},
            id="no-key",
        ),
        pytest.param(
            "[openai, gemini]",
            "",
            {"OPENAI_API_KEY": "placeholder", "GEMINI_API_KEY": "placeholder"},
            "gemini needs its model id under ai.available_models.gemini; the app would not start",
            "ai_model_id_missing",
            {"provider": "gemini"},
            id="no-model-id",
        ),
    ],
)
def test_a_model_offered_to_users_without_its_key_or_model_id_is_a_located_refusal(
    offered: str,
    gemini_model: str,
    keys: dict[str, str],
    message: str,
    code: str,
    params: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
        startup_settings(project, {SettingsFile.APPSETTING: text}, unsettled=0)

    [problem] = refused.value.problems
    line = at(text, f"user_selectable: {offered}")[0]
    assert (problem.file, problem.path, problem.line) == (SettingsFile.APPSETTING, "ai.user_selectable.1", line)
    assert (problem.message, problem.code, problem.params) == (message, code, params)


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
            project_with_shipped_settings(tmp_path), {SettingsFile.APPSETTING: text}, running_on(SystemEnvironment.DEV), unsettled=0
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
            project_with_shipped_settings(tmp_path),
            {SettingsFile.APPSETTING: text},
            running_on(SystemEnvironment.DEV, Audience.PUBLIC),
            unsettled=0,
        )

    [problem] = refused.value.problems
    assert (problem.file, problem.path, problem.line, problem.column) == (SettingsFile.APPSETTING, f"behavior.{flag}", *at(text, flag))
    assert problem.message.startswith("must be false on audience public")
    assert (problem.code, problem.params) == ("search_on_open_data", {"audience": "public"})


def test_a_personal_site_may_search_the_web_and_x(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    text = SHIPPED[SettingsFile.APPSETTING]
    text = text.replace("  enable_web_search: false", "  enable_web_search: true", 1).replace(
        "  enable_x_search: false", "  enable_x_search: true", 1
    )

    config = startup_settings(
        project_with_shipped_settings(tmp_path), {SettingsFile.APPSETTING: text}, running_on(SystemEnvironment.DEV), unsettled=0
    )

    assert (config.audience, config.behavior.enable_web_search, config.behavior.enable_x_search) == (Audience.PERSONAL, True, True)


def production_settings(registration_open: str) -> str:
    """The shipped settings in test on SinoPac's production server, with accounts.registration_open as given."""
    text = SHIPPED[SettingsFile.APPSETTING].replace("environment: dev", "environment: test", 1)
    text = text.replace("  server: simulation", "  server: production", 1)
    return text.replace("registration_open: false", f"registration_open: {registration_open}", 1)


def test_registration_ships_closed_and_the_production_server_refuses_to_start_with_it_open_naming_the_remedy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    project, text = project_with_shipped_settings(tmp_path), production_settings("true")
    open_in_dev = SHIPPED[SettingsFile.APPSETTING].replace("registration_open: false", "registration_open: true", 1)
    shipped, dev = (
        startup_settings(project, unsettled=0),
        startup_settings(project, {SettingsFile.APPSETTING: open_in_dev}, unsettled=0),
    )

    monkeypatch.setenv("ACCOUNTS_KEY", "A" * 43)

    with pytest.raises(InvalidSettingsError) as refused:
        startup_settings(project, {SettingsFile.APPSETTING: text}, unsettled=0)

    [problem] = refused.value.problems
    assert (problem.path, problem.line) == ("accounts.registration_open", at(text, "registration_open: true")[0])
    assert problem.message == (
        "shioaji.server production refuses accounts.registration_open: the site's SinoPac login is the real account. "
        "Close registration first"
    )
    assert (shipped.accounts.registration_open, dev.accounts.registration_open) == (False, True)
    assert not startup_settings(
        project, {SettingsFile.APPSETTING: production_settings("false")}, unsettled=0
    ).accounts.registration_open


def test_a_reload_that_moves_the_sinopac_server_needs_ordering_off_in_the_same_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    for credential in ShioajiServer.PRODUCTION.credentials:
        monkeypatch.setenv(credential.value, credential.value)
    project = project_with_shipped_settings(tmp_path)
    monkeypatch.chdir(project)
    moved = production_settings("false")
    ordering_on = moved.replace('sinopac_ordering: "off"', "sinopac_ordering: administrators", 1)
    on_simulation, on_production = (
        running_on(SystemEnvironment.TEST),
        running_on(SystemEnvironment.TEST, server=ShioajiServer.PRODUCTION),
    )

    with pytest.raises(InvalidSettingsError) as refused:
        startup_settings(project, {SettingsFile.APPSETTING: ordering_on}, on_simulation, unsettled=0)

    [problem] = refused.value.problems
    assert (problem.path, problem.line) == ("shioaji.server", at(ordering_on, "server: production")[0])
    assert (
        startup_settings(project, {SettingsFile.APPSETTING: moved}, on_simulation, unsettled=0).shioaji.server
        == ShioajiServer.PRODUCTION
    )
    assert startup_settings(project, {SettingsFile.APPSETTING: ordering_on}, on_production, unsettled=0), "the server stays"
    assert startup_settings(project, {SettingsFile.APPSETTING: ordering_on}, unsettled=0), "a start moves no login"


def test_a_switch_back_to_simulation_names_the_simulation_variables_it_lacks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    for credential in ShioajiServer.PRODUCTION.credentials:
        monkeypatch.setenv(credential.value, credential.value)
    for credential in ShioajiServer.SIMULATION.credentials:
        monkeypatch.delenv(credential.value, raising=False)
    project = project_with_shipped_settings(tmp_path)
    monkeypatch.chdir(project)
    back = SHIPPED[SettingsFile.APPSETTING].replace("environment: dev", "environment: test", 1)

    with pytest.raises(InvalidSettingsError) as refused:
        startup_settings(
            project, {SettingsFile.APPSETTING: back}, running_on(SystemEnvironment.TEST, server=ShioajiServer.PRODUCTION), unsettled=0
        )

    [problem] = refused.value.problems
    assert problem.message == (
        "shioaji.server simulation needs SHIOAJI_API_KEY_TEST, SHIOAJI_SECRET_KEY_TEST in the server's environment or .env"
    )


def test_no_variable_sets_the_sinopac_server_and_a_start_on_production_says_whether_ordering_is_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    monkeypatch.setenv("SHIOAJI_SERVER", "production")
    project = project_with_shipped_settings(tmp_path)
    monkeypatch.chdir(project)
    without_server = SHIPPED[SettingsFile.APPSETTING].replace("  server: simulation\n", "", 1)
    ordering_on = production_settings("false").replace('sinopac_ordering: "off"', "sinopac_ordering: administrators", 1)
    monkeypatch.setenv("ACCOUNTS_KEY", "A" * 43)

    with pytest.raises(InvalidSettingsError, match="shioaji.server: Field required"):
        startup_settings(project, {SettingsFile.APPSETTING: without_server}, unsettled=0)

    assert production_notice(startup_settings(project, {SettingsFile.APPSETTING: ordering_on}, unsettled=0)) == [
        "SinoPac's login is on the production server, real money: features.sinopac_ordering is administrators"
    ]
    assert production_notice(startup_settings(project, unsettled=0)) == []
