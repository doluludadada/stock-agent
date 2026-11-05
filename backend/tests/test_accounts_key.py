"""
Where the accounts key comes from at startup, as an operator sees it: ACCOUNTS_KEY when it is set, else
secrets/accounts.key under the project root, which the first start creates.
"""

import asyncio
import base64
import re
import secrets
import shutil
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import SecretStr
from support.fakes import RecordingLogger
from support.settings import PLACEHOLDER
from trading_stack import SilentLogger

from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import AccountsSetupError, InvalidSettingsError, startup_settings
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.user_dto import load_accounts_key
from c_infrastructure.database.repositories.user_store import AccountsKeyError, SqlUserStore
from c_infrastructure.system.attempt_log import MemoryAttemptLog
from d_presentation.dependencies import ProcessState, get_project_root, load_settings, open_runtime

PASSWORD = SecretStr("correct horse battery")


def new_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project root with no key file and no .env, ACCOUNTS_KEY unset, SQLite and Chroma inside it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ACCOUNTS_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", PLACEHOLDER)
    return tmp_path


def settings(project: Path) -> AppConfig:
    """The repository's settings, as startup loads them, run in `project`."""
    return load_settings(get_project_root()).model_copy(update={"project_root": project})


def key_file(project: Path) -> Path:
    return project / "secrets" / "accounts.key"


def write_key_file(project: Path, key: str) -> None:
    key_file(project).parent.mkdir(mode=0o700, exist_ok=True)
    key_file(project).write_text(f"{key}\n", encoding="utf-8")


def process(config: AppConfig, logger: ILoggingProvider) -> ProcessState:
    return ProcessState(logger=logger, attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())


async def set_up_administrator(config: AppConfig) -> None:
    async with open_runtime(config, process(config, SilentLogger())) as runtime:
        await runtime.signed_out.set_up_first_administrator("owner", "owner@example.com", PASSWORD)


@pytest.mark.asyncio
async def test_a_first_start_without_a_key_creates_a_private_key_file_and_starts(project: Path) -> None:
    config, logger = settings(project), RecordingLogger()

    async with open_runtime(config, process(config, logger)) as runtime:
        offer = await runtime.signed_out.load_sign_in_options()

    key = key_file(project).read_text(encoding="utf-8").strip()
    created = [message for _, message in logger.records if str(key_file(project)) in message]

    assert offer.needs_first_administrator
    assert len(base64.urlsafe_b64decode(key + "=")) == 32
    assert stat.S_IMODE(key_file(project).stat().st_mode) == 0o600
    assert stat.S_IMODE(key_file(project).parent.stat().st_mode) == 0o700
    assert len(created) == 1 and "Back it up with the database" in created[0]
    assert not any(key in message for _, message in logger.records)


@pytest.mark.asyncio
async def test_a_restart_reads_the_key_file_and_opens_the_same_users(project: Path) -> None:
    key = new_key()
    write_key_file(project, key)
    config = settings(project)
    await set_up_administrator(config)

    async with open_runtime(config, process(config, SilentLogger())) as runtime:
        user = await runtime.signed_out.sign_in("owner", PASSWORD, "cli")

    database = DatabaseConnector(config=config, logger=SilentLogger())
    saved = await SqlUserStore(database, SecretStr(key), SilentLogger()).verify_password("owner@example.com", PASSWORD)
    await database.close()

    assert user.username == "owner" and saved is not None and saved.user_id == user.user_id
    assert key_file(project).read_text(encoding="utf-8") == f"{key}\n"


def test_the_variable_wins_over_the_key_file(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    on_file, variable = new_key(), new_key()
    write_key_file(project, on_file)
    monkeypatch.setenv("ACCOUNTS_KEY", variable)

    assert load_accounts_key(settings(project), SilentLogger()).get_secret_value() == variable
    assert key_file(project).read_text(encoding="utf-8") == f"{on_file}\n"


def test_a_blank_variable_counts_as_unset(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCOUNTS_KEY", "  ")

    key = load_accounts_key(settings(project), SilentLogger())

    assert key.get_secret_value() == key_file(project).read_text(encoding="utf-8").strip()


@pytest.mark.asyncio
async def test_a_key_file_that_does_not_open_the_saved_users_refuses_the_start_and_names_the_file(project: Path) -> None:
    config = settings(project)
    await set_up_administrator(config)
    key_file(project).write_text(f"{new_key()}\n", encoding="utf-8")

    with pytest.raises(AccountsKeyError, match="Restore the original secrets/accounts.key"):
        async with open_runtime(config, process(config, SilentLogger())):
            pass


def test_a_malformed_key_refuses_the_start_and_names_where_it_came_from(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCOUNTS_KEY", "short")

    with pytest.raises(AccountsSetupError, match="^ACCOUNTS_KEY must be 32 random bytes"):
        load_accounts_key(settings(project), SilentLogger())

    monkeypatch.delenv("ACCOUNTS_KEY")
    write_key_file(project, "short")

    with pytest.raises(AccountsSetupError, match=f"^{re.escape(str(key_file(project)))} must be 32 random bytes"):
        load_accounts_key(settings(project), SilentLogger())


def test_prod_refuses_to_start_without_the_variable_where_it_is_set_and_never_creates_the_key_file(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copytree(get_project_root() / "config", project / "config")
    appsetting = project / "config" / "appsetting.yaml"
    text = appsetting.read_text(encoding="utf-8").replace("environment: dev", "environment: prod", 1)
    appsetting.write_text(text.replace("\n  backend: sqlite", "\n  backend: postgresql", 1), encoding="utf-8")
    for name in ("DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME"):
        monkeypatch.setenv(name, PLACEHOLDER)

    with pytest.raises(InvalidSettingsError) as refused:
        startup_settings(project)

    [problem] = refused.value.problems
    assert (problem.path, problem.line) == ("environment", text[: text.index("environment: prod")].count("\n") + 1)
    assert problem.message.startswith("environment prod needs ACCOUNTS_KEY in the environment or .env")

    with pytest.raises(AccountsSetupError, match="environment prod needs ACCOUNTS_KEY"):
        load_accounts_key(load_settings(project), SilentLogger())

    assert not key_file(project).exists()


def race(root: Path, starts: int) -> tuple[set[str], RecordingLogger]:
    """The keys of `starts` startups released at once on a project root with no key file, and what they logged."""
    config, logger, together = settings(root), RecordingLogger(), threading.Barrier(starts)

    def start(_: int) -> str:
        together.wait()
        return load_accounts_key(config, logger).get_secret_value()

    with ThreadPoolExecutor(starts) as pool:
        return set(pool.map(start, range(starts))), logger


def test_starts_racing_to_create_the_key_file_all_end_up_on_one_key(project: Path) -> None:
    for number in range(10):
        root = project / f"round-{number}"
        root.mkdir()
        keys, logger = race(root, starts=8)

        assert keys == {key_file(root).read_text(encoding="utf-8").strip()}
        assert [path.name for path in key_file(root).parent.iterdir()] == ["accounts.key"]
        assert len(logger.records) == 1
