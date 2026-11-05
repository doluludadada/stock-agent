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

from a_domain.types.enums import SettingsFile
from b_application.config.settings_loader import InvalidSettingsError, load_settings

BACKEND = Path(__file__).resolve().parents[1]
CONFIG = BACKEND.parent / "config"

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
        load_settings({SettingsFile.APPSETTING: appsetting} if appsetting else None)

    assert f"{location}: " in str(refused.value) and words in str(refused.value)
    assert SECRET not in "".join(traceback.format_exception(refused.value))


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
