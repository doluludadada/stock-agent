from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from a_domain.model.trading.account import AccountOpening
from d_presentation.web.schemas import (
    AccountAsOfResponse,
    AccountHistoryResponse,
    AccountValueResponse,
    ErrorResponse,
    ResetRequest,
    RunReference,
    TradeResponse,
)
from d_presentation.web.session import CurrentUser, MockBroker, PrivateAccess, RuntimeDependency, UserPipeline, WorkflowRunsDependency
from d_presentation.web.workflow_runs import RunInProgress

router = APIRouter(prefix="/account", tags=["Account"], dependencies=[PrivateAccess])


@router.get("/history")
async def get_account_history(pipeline: UserPipeline, runtime: RuntimeDependency, as_of: date | None = None) -> AccountHistoryResponse:
    """Menu 7: the account now, its equity curve, and the account at the end of `as_of`. It never orders and records no run."""
    status = await pipeline.load_account_history(as_of)
    snapshot = status.account_as_of

    return AccountHistoryResponse(
        current=AccountValueResponse.model_validate(status.account),
        live_stock_ids=sorted(status.live_stock_ids),
        equity_curve={day: AccountValueResponse.model_validate(account) for day, account in status.equity_curve.items()},
        as_of=None
        if snapshot is None
        else AccountAsOfResponse(last_fill_at=snapshot.taken_at, value=AccountValueResponse.model_validate(snapshot.account)),
        execution_provider=runtime.config.trading.execution_provider,
        order_mode=runtime.config.trading.order_mode,
        opening=status.account.opening,
        profit=status.account.profit,
    )


@router.get("/trades")
async def get_trades(
    pipeline: UserPipeline, limit: Annotated[int, Query(ge=1, le=100)] = 20, offset: Annotated[int, Query(ge=0, le=10_000)] = 0
) -> list[TradeResponse]:
    """
    Every order that filled at least one share since the mock account opened, newest first, each with the run whose
    decision it carried out: a follow's with the run it followed. Ask for limit + 1 to know of a next page.
    """
    trades = await pipeline.load_trades(limit, offset)
    return [TradeResponse(order=order, run=RunReference.model_validate(run)) for order, run in trades]


RESET: dict[int | str, dict[str, Any]] = {
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": "mock_broker_only: the execution provider is not the mock broker.",
    },
    status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "run_in_progress: a run of the user is still running."},
}


@router.post("/reset", dependencies=[MockBroker], responses=RESET)
async def reset_mock_account(
    body: ResetRequest, pipeline: UserPipeline, user: CurrentUser, runs: WorkflowRunsDependency
) -> AccountOpening:
    """
    Opens the user's mock account again with `initial_cash` and no positions; its equity curve and trades start anew
    and every decision is open to follow again. No run, decision or order is deleted. 409 while a run of the user
    runs, which could order on the account meanwhile.
    """
    if (running := runs.running(user.user_id)) is not None:
        raise RunInProgress(running)

    account = await pipeline.reset_mock_account(body.initial_cash)

    if account.opening is None:
        raise RuntimeError("the mock book reported no opening after its reset")

    return account.opening
