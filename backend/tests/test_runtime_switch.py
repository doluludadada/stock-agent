"""
The runtime switch: work holds the runtime it started on, a reload makes a new one current only once it started, and
a runtime no longer current closes when the last work holding it ends.
"""

import asyncio
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection
from support.databases import execute
from support.harness import ADMINISTRATOR, CliHarness, build_harness, rising_history, runtime_for
from trading_stack import run_stats

import c_infrastructure.database.models.schema_version_dto as schema_version
from a_domain.model.trading.account import Position
from a_domain.types.enums import Audience, ExecutionProvider, OrderStatus, RejectReason, SettingsFile, ShioajiServer
from a_domain.types.ids import RunId
from b_application.config.app_config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus
from c_infrastructure.database.models.schema_version_dto import SCHEMA_VERSION
from c_infrastructure.system.ordering_switch import SettingsFileOrderingSwitch
from d_presentation.dependencies import Runtime, compose_runtime, load_settings
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

    def __init__(self, failure: Exception | None = None, harness: CliHarness | None = None) -> None:
        self.harness = harness or build_harness()
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
    """
    Waits until every runtime but the current one has closed. It waits on the close itself: a real runtime closes its
    database connections, which takes time a count of loop turns can run out of on a slower machine.
    """
    earlier = switch.opened[:-1]

    try:
        async with asyncio.timeout(60):
            while any(opened.closing is None for opened in earlier):
                await asyncio.sleep(0)

            await asyncio.gather(*(opened.closing for opened in earlier if opened.closing is not None))
    except TimeoutError:
        raise AssertionError("an earlier runtime never closed") from None


async def test_a_reload_while_a_run_holds_the_old_runtime_closes_it_only_after_the_run(project: Path) -> None:
    opener = RecordingOpener()
    switch = await started(project, opener)

    with switch.hold() as run:
        edit(project, "temperature: 0.7", "temperature: 0.2")
        reload = await switch.reload()

        with switch.hold() as current:
            assert (run.runtime.config.ai.temperature, current.runtime.config.ai.temperature) == (0.7, 0.2)

        assert [opened.closed for opened in opener.opened] == [False, False]

    await drained(switch)

    assert isinstance(reload, SettingsReloaded)
    assert [opened.closed for opened in opener.opened] == [True, False] and switch.running == reload.revisions


async def test_turning_sinopac_ordering_off_stops_the_orders_of_a_sinopac_run_already_under_way(project: Path) -> None:
    edit(project, 'sinopac_ordering: "off"', "sinopac_ordering: administrators")
    harness = build_harness(sinopac=True)
    harness.list_stock("2317", rising_history(100.0), realtime_price=80.0)
    harness.real_broker.positions = [Position(stock_id="2317", quantity=1000, average_cost=100.0)]
    switch = await started(project, RecordingOpener(harness=harness))

    with switch.hold() as run:
        pipeline = run.runtime.pipeline_for(harness.administrator, ExecutionProvider.SHIOAJI)
        while_on = await pipeline.run_intraday()
        sent = list(harness.real_broker.placed)

        edit(project, "sinopac_ordering: administrators", 'sinopac_ordering: "off"')
        reload = await switch.reload()
        harness.real_broker.positions = [Position(stock_id="2317", quantity=1000, average_cost=100.0)]
        after_off = await pipeline.run_intraday()

    assert isinstance(reload, SettingsReloaded)
    assert [order.stock_id for order in sent] == ["2317"] and [order.status for order in while_on.orders] == [OrderStatus.FILLED]
    assert harness.real_broker.placed == sent and harness.broker.placed == []
    assert [(order.status, order.reason) for order in after_off.orders] == [
        (OrderStatus.REJECTED, f"{RejectReason.ORDERING_OFF.name}: this site has ordering on shioaji off: features.sinopac_ordering")
    ]


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

    assert opener.opened[0].closed is False

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
    running, asked, never = switch.running, asyncio.Event(), asyncio.Event()

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

    assert [opened.closed for opened in opener.opened] == [False, True] and switch.running == running


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
    running = switch.running

    edit(project, "  max_order_value: 100000", "  max_order_value: plenty")
    refused = await switch.reload()
    again = await switch.reload()

    assert isinstance(refused, ReloadRefused) and [problem.path for problem in refused.problems] == ["trading.max_order_value"]
    assert refused.problems[0].line is not None and again is None
    assert switch.running == running and len(opener.opened) == 1

    edit(project, "  max_order_value: plenty", "  max_order_value: 90000")
    reload = await switch.reload()

    with switch.hold() as current:
        assert reload is not None and current.runtime.config.trading.max_order_value == 90_000


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


@pytest.fixture
def real_project(project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The project copy started by the real opener: the session's database, placeholder keys, no .env."""
    monkeypatch.chdir(project)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    monkeypatch.setenv("ACCOUNTS_KEY", "A" * 43)
    return project


async def test_the_real_opener_reloads_a_valid_edit_and_closes_the_runtime_it_replaced(real_project: Path) -> None:
    async with open_runtime_switch(real_project) as switch:
        edit(real_project, "temperature: 0.7", "temperature: 0.2")
        reload = await switch.reload()
        await drained(switch)

        with switch.hold() as current:
            temperature = current.runtime.config.ai.temperature

    assert isinstance(reload, SettingsReloaded) and temperature == 0.2


async def an_upgrade_step(connection: AsyncConnection) -> None:
    """The step that makes the version before the code's one `just db-migrate` upgrades."""


async def test_a_reload_onto_a_database_of_an_older_schema_is_refused_and_the_running_runtime_stays(
    real_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(schema_version, "FIRST_SCHEMA_VERSION", SCHEMA_VERSION - 1)
    monkeypatch.setattr(schema_version, "UPGRADES", (an_upgrade_step,))

    async with open_runtime_switch(real_project) as switch:
        await execute(f"UPDATE schema_version SET version = {SCHEMA_VERSION - 1}")
        edit(real_project, "temperature: 0.7", "temperature: 0.2")
        refused = await switch.reload()

        with switch.hold() as current:
            temperature = current.runtime.config.ai.temperature

    assert refused is not None and temperature == 0.7
    [problem] = refused.problems
    assert f"The database is at schema version {SCHEMA_VERSION - 1}" in problem.message and "just db-migrate" in problem.message


@pytest.mark.parametrize("moment", ["before-the-order", "between-the-order-and-its-send"])
async def test_a_run_on_the_login_of_the_server_before_a_switch_orders_nothing_although_ordering_is_on_again(
    project: Path, moment: str
) -> None:
    """
    A run that started before a save switched shioaji.server keeps its runtime, whose login is on the old server. The
    settings on disk then name the other server with ordering on, as once an administrator turned it on again after the
    switch: the run's order is refused at its preparation, or right before its exchange order, never sent to the old login.
    """
    edit(project, 'sinopac_ordering: "off"', "sinopac_ordering: administrators")
    harness = build_harness(sinopac=True)
    harness.list_stock("2317", rising_history(100.0), realtime_price=80.0)
    harness.real_broker.positions = [Position(stock_id="2317", quantity=1000, average_cost=100.0)]
    config = harness.config.model_copy(update={"features": load_settings(project).features})
    dependencies = replace(harness.dependencies, ordering_switch=SettingsFileOrderingSwitch(project))
    pipeline = compose_runtime(config, harness.logger, harness.clock, dependencies).pipeline_for(
        harness.administrator, ExecutionProvider.SHIOAJI
    )

    if moment == "before-the-order":
        edit(project, "server: simulation", "server: production")
    else:
        harness.real_broker.before_send = lambda: edit(project, "server: simulation", "server: production")

    status = await pipeline.run_intraday()

    assert config.shioaji.server == ShioajiServer.SIMULATION and harness.real_broker.link().simulation is True
    assert harness.real_broker.placed == []
    assert [(order.status, order.reason) for order in status.orders] == [
        (
            OrderStatus.REJECTED,
            f"{RejectReason.BROKER_SERVER_MISMATCH.name}: the shioaji login is not on the production server shioaji.server "
            "names on disk now",
        )
    ]


async def test_a_process_that_never_reloads_stops_ordering_once_the_settings_on_disk_turn_sinopac_ordering_off(project: Path) -> None:
    """A CLI beside the Web API: its run keeps its own runtime, and another process's save reaches it through the files."""
    edit(project, 'sinopac_ordering: "off"', "sinopac_ordering: administrators")
    harness = build_harness(sinopac=True)
    harness.list_stock("2317", rising_history(100.0), realtime_price=80.0)
    harness.real_broker.positions = [Position(stock_id="2317", quantity=1000, average_cost=100.0)]
    config = harness.config.model_copy(update={"features": load_settings(project).features})
    dependencies = replace(harness.dependencies, ordering_switch=SettingsFileOrderingSwitch(project))
    pipeline = compose_runtime(config, harness.logger, harness.clock, dependencies).pipeline_for(
        harness.administrator, ExecutionProvider.SHIOAJI
    )

    while_on = await pipeline.run_intraday()
    sent = list(harness.real_broker.placed)
    edit(project, "sinopac_ordering: administrators", 'sinopac_ordering: "off"')
    harness.real_broker.positions = [Position(stock_id="2317", quantity=1000, average_cost=100.0)]
    after_off = await pipeline.run_intraday()

    assert [order.stock_id for order in sent] == ["2317"] and [order.status for order in while_on.orders] == [OrderStatus.FILLED]
    assert harness.real_broker.placed == sent
    assert [(order.status, order.reason) for order in after_off.orders] == [
        (OrderStatus.REJECTED, f"{RejectReason.ORDERING_OFF.name}: this site has ordering on shioaji off: features.sinopac_ordering")
    ]
