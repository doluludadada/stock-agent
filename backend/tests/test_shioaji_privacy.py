"""
The app imports the Shioaji SDK with its reporting off: no error of a production login goes to Sinopac's Sentry, and the
SDK's logger writes no shioaji.log into the working directory. Each check imports the SDK afresh, in its own process.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

FIRST_IMPORTS = {
    "the app's import": "from d_presentation.dependencies import import_shioaji; import_shioaji()",
    "the quote provider": "import c_infrastructure.market.shioaji_quote_provider",
    "the broker": "import c_infrastructure.trading.shioaji.execution_provider",
    "the tests' fake client": "import support.fake_shioaji",
}
"""Each way the SDK can be imported first in a process."""

PROBE = """
import json
import sentry_sdk
{first_import}
import shioaji.utils as sdk

sdk.set_error_tracking(simulation=False, error_tracking=True)
handlers = [getattr(handler, "baseFilename", type(handler).__name__) for handler in sdk.log.handlers]
print(json.dumps({"sentry": sentry_sdk.is_initialized(), "log_files": handlers}))
"""


def probe(folder: Path, first_import: str = FIRST_IMPORTS["the app's import"], **environment: str) -> dict[str, object]:
    """What the SDK did, imported by `first_import` in a new process working in `folder`, with `environment` set."""
    inherited = {name: value for name, value in os.environ.items() if name not in {"LOG_SENTRY", "SJ_LOG_PATH"}}
    answer = subprocess.run(
        [sys.executable, "-c", PROBE.replace("{first_import}", first_import)],
        cwd=folder,
        env=inherited | {"PYTHONPATH": f"{BACKEND / 'src'}:{BACKEND / 'tests'}"} | environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(answer.stdout.splitlines()[-1])


@pytest.mark.parametrize("first_import", FIRST_IMPORTS.values(), ids=FIRST_IMPORTS.keys())
def test_a_production_login_reports_nothing_to_sentry_and_the_sdk_writes_no_log_in_the_working_directory(
    tmp_path: Path, first_import: str
) -> None:
    assert probe(tmp_path, first_import) == {"sentry": False, "log_files": [os.devnull]}
    assert list(tmp_path.iterdir()) == []


def test_an_environment_that_names_a_log_file_keeps_it(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "shioaji.log"
    log_file.parent.mkdir()

    assert probe(tmp_path, SJ_LOG_PATH=str(log_file)) == {"sentry": False, "log_files": [str(log_file)]}
