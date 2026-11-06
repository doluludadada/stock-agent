from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from a_domain.model.trading.order import Order
from a_domain.types.enums import FollowRefusal
from a_domain.types.ids import RunId
from b_application.schemas.pipeline_status import PipelineStatus
from d_presentation.web.schemas import (
    Confirmed,
    ErrorResponse,
    FollowItem,
    FollowResponse,
    RunAccepted,
    RunResponse,
    SignalResponse,
    StockIdsRequest,
)
from d_presentation.web.session import (
    CurrentUser,
    MockBroker,
    NotFound,
    NothingToFollow,
    OutsideFollowWindow,
    PrivateAccess,
    QuoteLogin,
    RealtimeQuotes,
    RunStarter,
    UserPipeline,
    WorkflowRunsDependency,
)

router = APIRouter(prefix="/runs", tags=["Workflow runs"], dependencies=[PrivateAccess])

STARTED: dict[int | str, dict[str, Any]] = {
    status.HTTP_202_ACCEPTED: {"description": "The run started; poll GET /v1/runs/{run_id}."},
    status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "Another run of this user is still running."},
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponse,
        "description": "The server runs its most workflows at once; start yours later.",
    },
}

ORDERING: dict[int | str, dict[str, Any]] = {
    **STARTED,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": (
            "mock_broker_only: the execution provider is not the mock broker; use the CLI. realtime_quotes_unavailable: "
            "the site has no realtime quotes: it uses open data only (audience public), or it has no Shioaji login."
        ),
    },
}


@router.post("/full-cycle", status_code=status.HTTP_202_ACCEPTED, responses=STARTED)
async def start_full_cycle(body: Confirmed, pipeline: UserPipeline, user: CurrentUser, start: RunStarter) -> RunAccepted:
    """Starts menu 1: the after-market full-universe analysis. One AI call per stock that passes the strategy. It never orders."""
    return RunAccepted(run_id=start(user, lambda run_id: pipeline.run_full_cycle(run_id=run_id)))


@router.post("/specific-stocks", status_code=status.HTTP_202_ACCEPTED, responses=STARTED)
async def start_specific_stock_analysis(
    body: StockIdsRequest, pipeline: UserPipeline, user: CurrentUser, start: RunStarter
) -> RunAccepted:
    """Starts menu 4's analysis of the given stocks. Each stock is one AI call. It never orders; the API offers no manual BUY."""
    stock_ids = body.stock_ids
    return RunAccepted(run_id=start(user, lambda run_id: pipeline.analyse_specific_stocks(stock_ids, run_id=run_id)))


@router.post("/buzz-scan", status_code=status.HTTP_202_ACCEPTED, dependencies=[MockBroker, RealtimeQuotes], responses=ORDERING)
async def start_buzz_scan(body: Confirmed, pipeline: UserPipeline, user: CurrentUser, start: RunStarter) -> RunAccepted:
    """
    Starts menu 2, Social Buzz, on the mock broker only. Its decisions go through the same order gates and trading
    journal as the CLI's: a stop-loss SELL or a qualified BUY becomes a mock order. One AI call per qualified stock.
    """
    return RunAccepted(run_id=start(user, lambda run_id: pipeline.run_buzz_scan(run_id=run_id)))


@router.post("/intraday", status_code=status.HTTP_202_ACCEPTED, dependencies=[MockBroker, RealtimeQuotes], responses=ORDERING)
async def start_intraday(body: Confirmed, pipeline: UserPipeline, user: CurrentUser, start: RunStarter) -> RunAccepted:
    """Starts menu 3, Intraday, on the mock broker only, through the same order gates and journal as the CLI's."""
    return RunAccepted(run_id=start(user, lambda run_id: pipeline.run_intraday(run_id=run_id)))


FOLLOW_READ: dict[int | str, dict[str, Any]] = {
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": "mock_broker_only: the execution provider is not the mock broker.",
    },
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "The user has no such run."},
}

FOLLOWING: dict[int | str, dict[str, Any]] = {
    **STARTED,
    **FOLLOW_READ,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": (
            "mock_broker_only: the execution provider is not the mock broker. realtime_quotes_unavailable: the site prices "
            "orders on realtime quotes and has no Shioaji login now."
        ),
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": (
            "nothing_to_follow: no decision of the run is left to follow. outside_follow_window: the market is in a "
            "phase in which this site places no order. run_in_progress: another run of this user is still running."
        ),
    },
}


def refuse_follow(status: PipelineStatus) -> None:
    """404 for a run the user does not have; 409 with the refusal's own code for a follow that may not start now."""
    if status.followed_run is None:
        raise NotFound("No such run.")

    match status.follow_refusal:
        case FollowRefusal.NOTHING_TO_FOLLOW:
            raise NothingToFollow("No decision of this run is left to follow: each one is followed already, or it has none.")
        case FollowRefusal.OUTSIDE_FOLLOW_WINDOW:
            raise OutsideFollowWindow("This site places no order in the market's phase now. Follow the run when its window opens.")
        case None:
            return


@router.get("/{run_id}/follow", dependencies=[MockBroker], responses=FOLLOW_READ)
async def get_run_follow(run_id: UUID, pipeline: UserPipeline) -> FollowResponse:
    """What a follow of the run into the user's mock account may take now, and every follow of it so far. Records nothing."""
    status = await pipeline.load_follow(RunId(run_id))

    if status.followed_run is None:
        raise NotFound(f"No run {run_id}.")

    return FollowResponse(
        refusal=status.follow_refusal,
        open_decision_ids=[signal.decision_id for signal in status.followable_signals],
        follows=[FollowItem(decision=SignalResponse.model_validate(signal), order=order) for signal, order in status.follows],
    )


@router.post("/{run_id}/follow", status_code=status.HTTP_202_ACCEPTED, dependencies=[MockBroker, QuoteLogin], responses=FOLLOWING)
async def follow_run(run_id: UUID, body: Confirmed, pipeline: UserPipeline, user: CurrentUser, start: RunStarter) -> RunAccepted:
    """
    Follows the run's open decisions into the user's mock account, as a run of its own: each BUY with its shares, each
    SELL with at most the shares held, priced again now, through the same order gates and journal as every order. A
    second follow takes only the decisions no follow order of which filled since the account opened. A site that prices
    orders on realtime quotes refuses it while it has no Shioaji login, as it does Buzz and Intraday.
    """
    refuse_follow(await pipeline.load_follow(RunId(run_id)))
    followed = RunId(run_id)
    return RunAccepted(run_id=start(user, lambda follow_id: pipeline.follow_run(followed, run_id=follow_id)))


@router.get("")
async def list_runs(
    pipeline: UserPipeline,
    user: CurrentUser,
    runs: WorkflowRunsDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> list[RunResponse]:
    """Recorded runs, newest first, whichever entry point (CLI or API) started them. Ask for limit + 1 to know of a next page."""
    records = await pipeline.load_runs(limit, offset)
    return [response for record in records if (response := runs.describe(user.user_id, record.run_id, record)) is not None]


async def find_run(
    run_id: UUID, pipeline: UserPipeline, user: CurrentUser, runs: WorkflowRunsDependency
) -> tuple[RunResponse, PipelineStatus | None]:
    """The run as the API reports it and its recorded status, or 404 when neither the journal nor this server knows it."""
    recorded = await pipeline.load_run(RunId(run_id))
    response = runs.describe(
        user.user_id, RunId(run_id), recorded.stats if recorded else None, recorded.manual_stocks if recorded else []
    )

    if response is None:
        raise NotFound(f"No run {run_id}.")

    return response, recorded


@router.get("/{run_id}")
async def get_run(run_id: UUID, pipeline: UserPipeline, user: CurrentUser, runs: WorkflowRunsDependency) -> RunResponse:
    response, _ = await find_run(run_id, pipeline, user, runs)
    return response


@router.get("/{run_id}/signals")
async def get_run_signals(
    run_id: UUID, pipeline: UserPipeline, user: CurrentUser, runs: WorkflowRunsDependency
) -> list[SignalResponse]:
    """Every decision the run made, HOLD included, with the evidence it was made on."""
    _, recorded = await find_run(run_id, pipeline, user, runs)
    return [SignalResponse.model_validate(signal) for signal in (recorded.signals if recorded else [])]


@router.get("/{run_id}/orders")
async def get_run_orders(run_id: UUID, pipeline: UserPipeline, user: CurrentUser, runs: WorkflowRunsDependency) -> list[Order]:
    """Every order the run sent or refused, with its status, reason, fee, tax and realized PnL."""
    _, recorded = await find_run(run_id, pipeline, user, runs)
    return recorded.orders if recorded else []
