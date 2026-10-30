import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass

from a_domain.model.system.stats import SystemStats
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.ids import RunId, new_run_id
from b_application.schemas.pipeline_status import PipelineStatus
from d_presentation.web.schemas import RunResponse, RunState, RunSummary, StockReportResponse

KEPT_OUTCOMES = 100


class RunInProgress(Exception):
    def __init__(self, run_id: RunId) -> None:
        super().__init__(f"Run {run_id} is still running. Start the next run after it ends.")


@dataclass(frozen=True)
class RunOutcome:
    error: str | None = None
    reports: tuple[StockReportResponse, ...] = ()


class WorkflowRuns:
    """
    The workflow runs this server starts in the background, one at a time.

    The run record in the trading journal is the source of truth for a run. This keeps only what the record cannot
    say: which run is running here now, the exception that stopped a run (a run stopped by invalid technical settings
    has no record at all), and the reports of the stocks a specific-stock analysis was asked about, which the journal
    does not store. Outcomes of the latest KEPT_OUTCOMES runs are kept, in memory only.
    """

    def __init__(self, logger: ILoggingProvider) -> None:
        self._logger = logger
        self._running: tuple[RunId, asyncio.Task[None]] | None = None
        self._outcomes: dict[RunId, RunOutcome] = {}

    def start(self, workflow: Callable[[RunId], Awaitable[PipelineStatus]]) -> RunId:
        """Starts `workflow` under a new run id, which the workflow's run record takes, and returns that id at once."""
        if self._running is not None:
            raise RunInProgress(self._running[0])

        run_id = new_run_id()
        self._running = run_id, asyncio.create_task(self._run(run_id, workflow))

        return run_id

    def describe(self, run_id: RunId, record: SystemStats | None) -> RunResponse | None:
        """The run as the API reports it, or None when neither the journal nor this server knows it."""
        outcome = self._outcomes.get(run_id)

        if record is None and outcome is None and not self._is_running(run_id):
            return None

        if self._is_running(run_id):
            state = RunState.RUNNING
        elif outcome is not None and outcome.error is not None:
            state = RunState.FAILED
        elif record is not None and record.end_time is None:
            state = RunState.UNFINISHED
        else:
            state = RunState.FINISHED

        return RunResponse(
            run_id=run_id,
            state=state,
            error=outcome.error if outcome else None,
            summary=RunSummary.model_validate(record) if record else None,
            reports=list(outcome.reports) if outcome else [],
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
            status = await workflow(run_id)
            outcome = RunOutcome(reports=tuple(StockReportResponse.model_validate(stock) for stock in status.manual_stocks))

        except Exception as error:
            self._logger.error(f"Run {run_id} stopped: {type(error).__name__}: {error}")
            outcome = RunOutcome(error=f"{type(error).__name__}: {error}")

        finally:
            self._running = None

        self._outcomes[run_id] = outcome

        while len(self._outcomes) > KEPT_OUTCOMES:
            del self._outcomes[next(iter(self._outcomes))]
