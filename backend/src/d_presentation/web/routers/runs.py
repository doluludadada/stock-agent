from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from a_domain.types.ids import RunId
from b_application.schemas.pipeline_status import PipelineStatus
from d_presentation.dependencies import RuntimeDependency, WorkflowRunsDependency, WritePermission
from d_presentation.web.schemas import Confirmed, OrderResponse, RunAccepted, RunResponse, SignalResponse, StockIdsRequest
from d_presentation.web.workflow_runs import RunInProgress, WorkflowRuns

router = APIRouter(prefix="/runs", tags=["Workflow runs"])

STARTED: dict[int | str, dict[str, Any]] = {
    status.HTTP_202_ACCEPTED: {"description": "The run started; poll GET /v1/runs/{run_id}."},
    status.HTTP_409_CONFLICT: {"description": "Another run started by this server is still running."},
}


def start(runs: WorkflowRuns, workflow: Callable[[RunId], Awaitable[PipelineStatus]]) -> RunAccepted:
    try:
        return RunAccepted(run_id=runs.start(workflow))

    except RunInProgress as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error


@router.post("/full-cycle", status_code=status.HTTP_202_ACCEPTED, dependencies=[WritePermission], responses=STARTED)
async def start_full_cycle(body: Confirmed, runtime: RuntimeDependency, runs: WorkflowRunsDependency) -> RunAccepted:
    """Starts menu 1: the after-market full-universe analysis. It never orders."""
    return start(runs, lambda run_id: runtime.pipeline.run_full_cycle(run_id=run_id))


@router.post("/specific-stocks", status_code=status.HTTP_202_ACCEPTED, dependencies=[WritePermission], responses=STARTED)
async def start_specific_stock_analysis(
    body: StockIdsRequest, runtime: RuntimeDependency, runs: WorkflowRunsDependency
) -> RunAccepted:
    """Starts menu 4's analysis of the given stocks. Each stock is one AI call. It never orders; the API offers no manual BUY."""
    return start(runs, lambda run_id: runtime.pipeline.analyse_specific_stocks(body.stock_ids, run_id=run_id))


@router.get("")
async def list_runs(
    runtime: RuntimeDependency, runs: WorkflowRunsDependency, limit: Annotated[int, Query(ge=1, le=200)] = 20
) -> list[RunResponse]:
    """The latest recorded runs, newest first, whichever entry point (CLI or API) started them."""
    records = await runtime.journal.recent_runs(limit)
    return [response for record in records if (response := runs.describe(record.run_id, record)) is not None]


async def find_run(run_id: UUID, runtime: RuntimeDependency, runs: WorkflowRunsDependency) -> RunResponse:
    response = runs.describe(RunId(run_id), await runtime.journal.find_run(RunId(run_id)))

    if response is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No run {run_id}.")

    return response


@router.get("/{run_id}")
async def get_run(run_id: UUID, runtime: RuntimeDependency, runs: WorkflowRunsDependency) -> RunResponse:
    return await find_run(run_id, runtime, runs)


@router.get("/{run_id}/signals")
async def get_run_signals(run_id: UUID, runtime: RuntimeDependency, runs: WorkflowRunsDependency) -> list[SignalResponse]:
    """Every decision the run made, HOLD included, with the evidence it was made on."""
    await find_run(run_id, runtime, runs)
    signals = await runtime.journal.signals_of(RunId(run_id))
    return [SignalResponse.model_validate({**signal.model_dump(), "run_id": run_id}) for signal in signals]


@router.get("/{run_id}/orders")
async def get_run_orders(run_id: UUID, runtime: RuntimeDependency, runs: WorkflowRunsDependency) -> list[OrderResponse]:
    """Every order the run sent or refused, with its status, reason, fee, tax and realized PnL."""
    await find_run(run_id, runtime, runs)
    return [OrderResponse.model_validate(order) for order in await runtime.journal.orders_of(RunId(run_id))]
