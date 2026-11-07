from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from a_domain.model.trading.account import AccountOpening
from a_domain.types.enums import ExecutionProvider
from d_presentation.web.schemas import (
    AccountAsOfResponse,
    AccountHistoryResponse,
    AccountValueResponse,
    BrokerResponse,
    ErrorResponse,
    ResetRequest,
    RunReference,
    TradeResponse,
)
from d_presentation.web.session import (
    BrokerPipeline,
    CurrentUser,
    PrivateAccess,
    RuntimeDependency,
    UserPipeline,
    WorkflowRunsDependency,
)
from d_presentation.web.workflow_runs import RunInProgress

router = APIRouter(prefix="/account", tags=["Account"], dependencies=[PrivateAccess])


BROKER_READ: dict[int | str, dict[str, Any]] = {
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": (
            "real_broker_refused: a real broker's account, asked by a user who is not an administrator. "
            "broker_unavailable: the real broker has no login up on this site now."
        ),
    }
}


@router.get("/brokers")
async def get_brokers(runtime: RuntimeDependency, user: CurrentUser) -> list[BrokerResponse]:
    """
    The brokers the user may choose for Buzz, Intraday or a manual BUY now, the mock account first, each with what a
    run's confirmation names: a real broker's server and its BUY limits.
    """
    config = runtime.config
    return [
        BrokerResponse(
            broker=broker,
            simulation=config.environment.shioaji_simulation if broker.real else None,
            max_order_value=config.trading.max_order_value if broker.real else None,
            max_daily_buy_value=config.trading.max_daily_buy_value if broker.real else None,
        )
        for broker in runtime.brokers_for(user)
    ]


@router.get("/history", responses=BROKER_READ)
async def get_account_history(
    pipeline: BrokerPipeline, broker: ExecutionProvider = ExecutionProvider.MOCK, as_of: date | None = None
) -> AccountHistoryResponse:
    """
    Menu 7 on the `broker` account, the mock account by default: the account now, its equity curve, and the account at
    the end of `as_of`. It never orders and records no run.
    """
    status = await pipeline.load_account_history(as_of)
    snapshot = status.account_as_of

    return AccountHistoryResponse(
        current=AccountValueResponse.model_validate(status.account),
        live_stock_ids=sorted(status.live_stock_ids),
        equity_curve={day: AccountValueResponse.model_validate(account) for day, account in status.equity_curve.items()},
        as_of=None
        if snapshot is None
        else AccountAsOfResponse(last_fill_at=snapshot.taken_at, value=AccountValueResponse.model_validate(snapshot.account)),
        execution_provider=broker,
        opening=status.account.opening,
        profit=status.account.profit,
    )


@router.get("/trades", responses=BROKER_READ)
async def get_trades(
    pipeline: BrokerPipeline, limit: Annotated[int, Query(ge=1, le=100)] = 20, offset: Annotated[int, Query(ge=0, le=10_000)] = 0
) -> list[TradeResponse]:
    """
    Every order of a run on the `broker` account (the mock account by default) that filled at least one share, since
    the mock account opened or every one at a real broker, newest first, each with the run whose decision it carried
    out: a follow's with the run it followed. Ask for limit + 1 to know of a next page.
    """
    trades = await pipeline.load_trades(limit, offset)
    return [TradeResponse(order=order, run=RunReference.model_validate(run)) for order, run in trades]


RESET: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "run_in_progress: a run of the user is still running."}
}


@router.post("/reset", responses=RESET)
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
