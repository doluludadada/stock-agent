from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from a_domain.types.ids import BacktestId
from d_presentation.web.schemas import (
    BacktestOptionsResponse,
    BacktestRequest,
    BacktestResponse,
    BacktestSummary,
    Confirmed,
    ErrorResponse,
)
from d_presentation.web.session import NotFound, PrivateAccess, UserPipeline

router = APIRouter(prefix="/backtests", tags=["Backtests"], dependencies=[PrivateAccess])

REFUSED: dict[int | str, dict[str, Any]] = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": (
            "invalid_request: a field of the body does not validate, and `detail` lists each one. "
            "backtest_period_unavailable: the period reaches outside the days the site's daily history can replay, or "
            "holds no session; `detail` says which days a backtest may cover."
        ),
    }
}

UNKNOWN: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "The user has no saved backtest of that id."}
}


@router.get("/options")
async def get_backtest_options(pipeline: UserPipeline) -> BacktestOptionsResponse:
    """
    What the user may ask a backtest for: the strategy it would replay, and the inputs of the longest one the site's
    daily history allows at the live settings. A backtest reads only sessions the site already holds.
    """
    strategy, inputs = await pipeline.load_backtest_options()

    return BacktestOptionsResponse(strategy_id=strategy.strategy_id, strategy_name=strategy.name, inputs=inputs)


@router.post("", responses=REFUSED)
async def run_backtest(body: BacktestRequest, pipeline: UserPipeline) -> BacktestResponse:
    """
    Replays the user's active technical strategy over the period, day by day with the live trading rules, and answers
    the backtest, saved for the user. A stock is decided on its technical score alone, as a run decides a stock the AI
    is not asked about; a decision made after one session's close fills at the next open. It asks no AI, touches no
    account and never orders. The answer comes when the replay is done: seconds, longer for the first one after a start.
    """
    return BacktestResponse.model_validate(await pipeline.run_backtest(body.inputs))


@router.get("")
async def get_backtests(pipeline: UserPipeline) -> list[BacktestSummary]:
    """The user's saved backtests, newest first: the site keeps the newest accounts.saved_backtests of each user."""
    return [BacktestSummary.model_validate(backtest) for backtest in await pipeline.load_backtests()]


@router.get("/{backtest_id}", responses=UNKNOWN)
async def get_backtest(backtest_id: UUID, pipeline: UserPipeline) -> BacktestResponse:
    """One saved backtest of the user, with its days and trades. Another user's id answers 404."""
    backtest = await pipeline.load_backtest(BacktestId(backtest_id))

    if backtest is None:
        raise NotFound(f"No saved backtest {backtest_id}.")

    return BacktestResponse.model_validate(backtest)


@router.post("/{backtest_id}/delete", status_code=status.HTTP_204_NO_CONTENT, responses=UNKNOWN)
async def delete_backtest(backtest_id: UUID, body: Confirmed, pipeline: UserPipeline) -> None:
    """Deletes one saved backtest of the user. Another user's id answers 404 and deletes nothing."""
    if not await pipeline.delete_backtest(BacktestId(backtest_id)):
        raise NotFound(f"No saved backtest {backtest_id}.")
