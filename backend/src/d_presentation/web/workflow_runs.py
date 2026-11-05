import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.ids import RunId, new_run_id
from b_application.schemas.pipeline_status import PipelineStatus
from d_presentation.web.schemas import RunResponse, RunState, RunSummary, StockReportResponse

KEPT_ERRORS = 100


class RunInProgress(Exception):
    def __init__(self, run_id: RunId) -> None:
        super().__init__(f"Run {run_id} is still running. Start the next run after it ends.")


class WorkflowRuns:
    """
    The workflow runs this server starts in the background, one at a time per process, so the server runs with one
    worker. It is not a lock across processes: a CLI on the same database can run at the same time.

    The run record and the stock reports in the trading journal are the source of truth for a run, its failure
    included. This keeps only what the journal cannot say: which run is running here now, and the exception that
    stopped a run, which the API reports for a run that has no record (invalid technical settings stop a run before it
    is recorded), for the latest KEPT_ERRORS failed runs, in memory only. After a restart, a run whose process stopped
    reads as unfinished from its record.
    """

    def __init__(self, logger: ILoggingProvider) -> None:
        self._logger = logger
        self._running: tuple[RunId, asyncio.Task[None]] | None = None
        self._failures: dict[RunId, str] = {}

    def start(self, workflow: Callable[[RunId], Awaitable[PipelineStatus]]) -> RunId:
        """Starts `workflow` under a new run id, which the workflow's run record takes, and returns that id at once."""
        if self._running is not None:
            raise RunInProgress(self._running[0])

        run_id = new_run_id()
        self._running = run_id, asyncio.create_task(self._run(run_id, workflow))

        return run_id

    @property
    def running_run_id(self) -> RunId | None:
        return self._running[0] if self._running else None

    def describe(self, run_id: RunId, record: SystemStats | None, stocks: list[Stock] | None = None) -> RunResponse | None:
        """The run as the API reports it, or None when neither the journal nor this server knows it."""
        failure = record.failure if record is not None else self._failures.get(run_id)

        if record is None and failure is None and not self._is_running(run_id):
            return None

        if self._is_running(run_id):
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
        """Cancels the running run at shutdown; RunHistory records it as aborted while the database is still open."""
        if self._running is None:
            return

        task = self._running[1]
        task.cancel()

        with suppress(asyncio.CancelledError):
            await task

    def _is_running(self, run_id: RunId) -> bool:
        return self._running is not None and self._running[0] == run_id

    async def _run(self, run_id: RunId, workflow: Callable[[RunId], Awaitable[PipelineStatus]]) -> None:
        try:
            await workflow(run_id)
            return

        except Exception as error:
            self._logger.error(f"Run {run_id} stopped: {type(error).__name__}: {error}")
            self._failures[run_id] = f"{type(error).__name__}: {error}"

        finally:
            self._running = None

        while len(self._failures) > KEPT_ERRORS:
            del self._failures[next(iter(self._failures))]
