"""
The runtime switch: work holds the runtime it started on, a reload makes a new one current only once it started, and
a runtime no longer current closes when the last work holding it ends.
"""

import asyncio
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from support.harness import ADMINISTRATOR, build_harness, runtime_for
from trading_stack import run_stats

from a_domain.types.enums import Audience, SettingsFile
from a_domain.types.ids import RunId
from b_application.config.app_config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus
from c_infrastructure.database.models.schema_version_dto import SCHEMA_VERSION
from d_presentation.dependencies import Runtime, load_settings
from d_presentation.live_runtime import ReloadRefused, RuntimeSwitch, SettingsReloaded, open_runtime_switch
from d_presentation.web.schemas import RunState
from d_presentation.web.workflow_runs import RunInProgress, WorkflowRuns

pytestmark = pytest.mark.asyncio

REPOSITORY_CONFIG = Path(__file__).resolve().parents[2] / "config"


@dataclass
class Opened:
    config: AppConfig
    closed: bool = False


class RecordingOpener:
    """Opens a runtime over the harness's fakes for each config and records when the runtime it opened closes."""

    def __init__(self, failure: Exception | None = None) -> None:
        self.harness = build_harness()
        self.opened: list[Opened] = []
        self.failure = failure

    @asynccontextmanager
    async def __call__(self, config: AppConfig) -> AsyncIterator[Runtime]:
        record = Opened(config)
        self.opened.append(record)

        try:
            if self.failure is not None:
                raise self.failure

            yield runtime_for(self.harness, config)
        finally:
            record.closed = True


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of config/, with a placeholder key for the active AI provider, which every start and reload needs."""
    shutil.copytree(REPOSITORY_CONFIG, tmp_path / "config")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    return tmp_path


def edit(project: Path, old: str, new: str) -> None:
    path = project / "config" / SettingsFile.APPSETTING.file_name
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


async def started(project: Path, opener: RecordingOpener) -> RuntimeSwitch:
    switch = RuntimeSwitch(opener, project, opener.harness.logger)
    await switch.start(load_settings(project))
    return switch


async def ended(runs: WorkflowRuns, run_id: RunId) -> None:
    """Waits until the administrator's run is no longer running, and fails the test when it failed."""
    for _ in range(1000):
        response = runs.describe(ADMINISTRATOR.user_id, run_id, None)

        if response is None or response.state != RunState.RUNNING:
            assert response is None or response.error is None, response.error
            return

        await asyncio.sleep(0)

    raise AssertionError("the run never ended")


async def drained(switch: RuntimeSwitch) -> None:
    """Waits until no earlier runtime is still open, as the editor's status reports it."""
    for _ in range(1000):
        if switch.status.draining == 0:
            return

        await asyncio.sleep(0)

    raise AssertionError("an earlier runtime never closed")


async def test_a_reload_while_a_run_holds_the_old_runtime_closes_it_only_after_the_run(project: Path) -> None:
    opener = RecordingOpener()
    switch = await started(project, opener)

    with switch.hold() as run:
        edit(project, "temperature: 0.7", "temperature: 0.2")
        reload = await switch.reload()

        with switch.hold() as current:
            assert (run.runtime.config.ai.temperature, current.runtime.config.ai.temperature) == (0.7, 0.2)

        assert [opened.closed for opened in opener.opened] == [False, False] and switch.status.draining == 1

    await drained(switch)

    assert isinstance(reload, SettingsReloaded)
    assert [opened.closed for opened in opener.opened] == [True, False]
    assert switch.status.running == reload.revisions and switch.status.draining == 0


async def test_a_run_its_request_started_keeps_a_retired_runtime_open_until_the_run_ends(project: Path) -> None:
    opener = RecordingOpener()
    switch = await started(project, opener)
    runs, finish = WorkflowRuns(opener.harness.logger), asyncio.Event()

    async def workflow(run_id: RunId) -> PipelineStatus:
        await finish.wait()
        return PipelineStatus(stats=run_stats())

    with switch.hold() as request:
        run_id = runs.start(ADMINISTRATOR, request.hold(), workflow, 2)

    edit(project, "temperature: 0.7", "temperature: 0.2")
    await switch.reload()

    assert opener.opened[0].closed is False and switch.status.draining == 1

    finish.set()
    await ended(runs, run_id)
    await drained(switch)

    assert opener.opened[0].closed is True


async def test_a_refused_run_takes_no_hold_and_a_run_cancelled_before_its_first_step_gives_its_hold_back(project: Path) -> None:
    opener = RecordingOpener()
    switch = await started(project, opener)
    runs, finish = WorkflowRuns(opener.harness.logger), asyncio.Event()

    async def workflow(run_id: RunId) -> PipelineStatus:
        await finish.wait()
        return PipelineStatus(stats=run_stats())

    with switch.hold() as request:
        runs.start(ADMINISTRATOR, request.hold(), workflow, 2)

        with pytest.raises(RunInProgress):
            runs.start(ADMINISTRATOR, request.hold(), workflow, 2)

    edit(project, "temperature: 0.7", "temperature: 0.2")
    await switch.reload()
    finish.set()
    await runs.stop()
    await drained(switch)

    assert [opened.closed for opened in opener.opened] == [True, False]


async def test_a_reload_cancelled_after_its_runtime_opened_closes_that_runtime_and_keeps_the_current_one(project: Path) -> None:
    opener = RecordingOpener()
    switch = await started(project, opener)
    running, asked, never = switch.status.running, asyncio.Event(), asyncio.Event()

    async def user_count() -> int:
        asked.set()
        await never.wait()
        return 1

    opener.harness.users.user_count = user_count
    edit(project, "temperature: 0.7", "temperature: 0.2")
    reload = asyncio.create_task(switch.reload())

    async with asyncio.timeout(10):
        await asked.wait()

    reload.cancel()

    with pytest.raises(asyncio.CancelledError):
        await reload

    assert [opened.closed for opened in opener.opened] == [False, True] and switch.status.running == running


async def test_refresh_twice_changes_nothing_the_second_time(project: Path) -> None:
    opener = RecordingOpener()
    switch = await started(project, opener)

    assert await switch.reload() is None

    edit(project, "temperature: 0.7", "temperature: 0.2")
    first, second = await switch.reload(), await switch.reload()

    assert (first is not None, second, len(opener.opened)) == (True, None, 2)


async def test_a_refused_edit_on_disk_keeps_the_runtime_and_is_tried_again_only_when_the_files_change(project: Path) -> None:
    opener = RecordingOpener()
    switch = await started(project, opener)
    running = switch.status.running

    edit(project, "  order_mode: mock_only", "  order_mode: sometimes")
    refused = await switch.reload()
    again = await switch.reload()

    assert isinstance(refused, ReloadRefused) and [problem.path for problem in refused.problems] == ["trading.order_mode"]
    assert refused.problems[0].line is not None and again is None
    assert switch.status.running == running and switch.status.refused == refused
    assert len(opener.opened) == 1

    edit(project, "  order_mode: sometimes", "  order_mode: disabled")
    reload = await switch.reload()

    with switch.hold() as current:
        assert reload is not None and current.runtime.config.trading.order_mode.value == "disabled"

    assert switch.status.refused is None


async def test_a_reload_that_changes_the_audience_is_refused_and_the_runtime_keeps_the_audience_it_started_on(project: Path) -> None:
    opener = RecordingOpener()
    switch = await started(project, opener)

    edit(project, "audience: personal", "audience: public")
    refused = await switch.reload()

    assert isinstance(refused, ReloadRefused) and [problem.path for problem in refused.problems] == ["audience"]
    assert refused.problems[0].message.endswith("the audience changes only when the app restarts")
    with switch.hold() as current:
        assert current.runtime.config.audience == Audience.PERSONAL
    assert len(opener.opened) == 1


async def test_a_runtime_that_fails_to_open_closes_what_it_opened_and_the_current_one_keeps_serving(project: Path) -> None:
    opener = RecordingOpener()
    switch = await started(project, opener)
    opener.failure = ConnectionRefusedError("connect to user:secret@db.example failed")

    edit(project, "temperature: 0.7", "temperature: 0.2")
    refused = await switch.reload()

    assert isinstance(refused, ReloadRefused) and [problem.message for problem in refused.problems] == [
        "The app would not start: ConnectionRefusedError. The server log has the details."
    ]
    assert [opened.closed for opened in opener.opened] == [False, True]

    with switch.hold() as current:
        assert current.runtime.config.ai.temperature == 0.7


async def test_a_retry_loads_refused_files_that_did_not_change_once_the_cause_outside_them_is_gone(project: Path) -> None:
    opener = RecordingOpener(failure=None)
    switch = await started(project, opener)
    opener.failure = ConnectionRefusedError("the database is down")

    edit(project, "temperature: 0.7", "temperature: 0.2")
    refused, unchanged = await switch.reload(), await switch.reload()
    opener.failure = None
    retried = await switch.retry()

    with switch.hold() as current:
        temperature = current.runtime.config.ai.temperature

    assert isinstance(refused, ReloadRefused) and unchanged is None and isinstance(retried, SettingsReloaded)
    assert temperature == 0.2 and switch.status.refused is None


@pytest.fixture
def real_project(project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The project copy started by the real opener: SQLite and Chroma inside it, placeholder keys, no .env."""
    monkeypatch.chdir(project)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    monkeypatch.setenv("ACCOUNTS_KEY", "A" * 43)
    edit(project, 'chroma_persist_path: "chroma_data"', f'chroma_persist_path: "{project / "chroma"}"')
    return project


async def test_the_real_opener_reloads_a_valid_edit_and_closes_the_runtime_it_replaced(real_project: Path) -> None:
    async with open_runtime_switch(real_project) as switch:
        edit(real_project, "temperature: 0.7", "temperature: 0.2")
        reload = await switch.reload()
        await drained(switch)

        with switch.hold() as current:
            temperature = current.runtime.config.ai.temperature

    assert isinstance(reload, SettingsReloaded) and temperature == 0.2


async def test_a_reload_onto_a_database_of_an_older_schema_is_refused_and_the_running_runtime_stays(real_project: Path) -> None:
    async with open_runtime_switch(real_project) as switch:
        engine = create_async_engine(f"sqlite+aiosqlite:///{real_project / 'stock_agent.db'}")

        async with engine.begin() as connection:
            await connection.execute(text("UPDATE schema_version SET version = :older"), {"older": SCHEMA_VERSION - 1})

        await engine.dispose()
        edit(real_project, "temperature: 0.7", "temperature: 0.2")
        refused = await switch.reload()

        with switch.hold() as current:
            temperature = current.runtime.config.ai.temperature

    assert refused is not None and temperature == 0.7 and switch.status.draining == 0
    [problem] = refused.problems
    assert f"The database is at schema version {SCHEMA_VERSION - 1}" in problem.message and "just db-migrate" in problem.message
