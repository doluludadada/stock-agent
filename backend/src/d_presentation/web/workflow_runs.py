import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager, ExitStack, suppress

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.system.user import User
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import Permission
from a_domain.types.ids import RunId, UserId, new_run_id
from b_application.schemas.pipeline_status import PipelineStatus
from d_presentation.web.schemas import RunResponse, RunState, RunSummary, StockReportResponse

KEPT_ERRORS = 100


class RunInProgress(Exception):
    def __init__(self, run_id: RunId) -> None:
        super().__init__(f"Your run {run_id} is still running. Start the next run after it ends.")


class TooManyRuns(Exception):
    def __init__(self, running: int) -> None:
        super().__init__(f"The server runs {running} workflows already. Start yours after one of them ends.")


class WorkflowRuns:
    """
    The workflow runs this server starts in the background: one at a time per user, and at most
    accounts.max_concurrent_runs of the settings a run starts on, every user's together, when a user without
    UNCAPPED_RUNS starts one, in one process, so the server runs with one worker.
    Different users' runs read and write disjoint rows, their own mock account included, so they need no lock. It is
    not a lock across processes: a user's CLI run on the same database can run beside their Web run.

    The run record and the stock reports in the trading journal are the source of truth for a run, its failure
    included. This keeps only what the journal cannot say: which runs are running here now, and the exception that
    stopped a run, which the API reports for a run that has no record (invalid technical settings stop a run before it
    is recorded), for the latest KEPT_ERRORS failed runs, in memory only, each known only to the user who started it.
    After a restart, a run whose process stopped reads as unfinished from its record.
    """

    def __init__(self, logger: ILoggingProvider) -> None:
        self._logger = logger
        self._running: dict[UserId, tuple[RunId, asyncio.Task[None]]] = {}
        self._failures: dict[tuple[UserId, RunId], str] = {}

    def start(
        self,
        user: User,
        hold: AbstractContextManager[object],
        workflow: Callable[[RunId], Awaitable[PipelineStatus]],
        max_running: int,
    ) -> RunId:
        """
        Starts `workflow` under a new run id, which the workflow's run record takes, and returns that id at once. The
        workflow holds its user's own Pipeline, so the run stays theirs after a sign-out or a deactivation mid-run.
        RunInProgress while the user's run runs; TooManyRuns while the server runs `max_running` already, the cap of
        the settings the run starts on, never for an administrator. `hold` keeps the runtime the run's Pipeline came
        from open: a started run enters it here, before its request's own hold can end, and leaves it once its task is
        done, however it ended, a cancel before its first step included; a refused run never enters it.
        """
        if (running := self._running.get(user.user_id)) is not None:
            raise RunInProgress(running[0])

        if len(self._running) >= max_running and Permission.UNCAPPED_RUNS not in user.permissions:
            raise TooManyRuns(len(self._running))

        held = ExitStack()
        held.enter_context(hold)
        run_id = new_run_id()
        task = asyncio.create_task(self._run(user.user_id, run_id, workflow))
        task.add_done_callback(lambda _: held.close())
        self._running[user.user_id] = run_id, task

        return run_id

    def describe(
        self, owner_id: UserId, run_id: RunId, record: SystemStats | None, stocks: list[Stock] | None = None
    ) -> RunResponse | None:
        """
        The run as the API reports it to its user, or None when neither the user's journal nor this server knows it: a
        run of another user is unknown, running or failed.
        """
        failure = record.failure if record is not None else self._failures.get((owner_id, run_id))
        running = self._is_running(owner_id, run_id)

        if record is None and failure is None and not running:
            return None

        if running:
            state = RunState.RUNNING
        elif failure is not None:
            state = RunState.FAILED
        elif record is not None and record.end_time is None:
            state = RunState.UNFINISHED
        else:
            state = RunState.FINISHED

        return RunResponse(
            run_id=run_id,
            state=state,
            error=failure,
            summary=RunSummary.model_validate(record) if record else None,
            reports=[StockReportResponse.model_validate(stock) for stock in stocks or []],
        )

    async def stop(self) -> None:
        """Cancels every running run at shutdown; RunHistory records each as aborted while the database is still open."""
        tasks = [task for _, task in self._running.values()]

        for task in tasks:
            task.cancel()

        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

    def _is_running(self, owner_id: UserId, run_id: RunId) -> bool:
        running = self._running.get(owner_id)
        return running is not None and running[0] == run_id

    async def _run(self, owner_id: UserId, run_id: RunId, workflow: Callable[[RunId], Awaitable[PipelineStatus]]) -> None:
        try:
            await workflow(run_id)
            return

        except Exception as error:
            self._logger.error(f"Run {run_id} stopped: {type(error).__name__}: {error}")
            self._failures[owner_id, run_id] = f"{type(error).__name__}: {error}"

        finally:
            del self._running[owner_id]

        while len(self._failures) > KEPT_ERRORS:
            del self._failures[next(iter(self._failures))]
