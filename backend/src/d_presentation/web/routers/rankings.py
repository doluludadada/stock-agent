from datetime import date
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel

from a_domain.rules.trading.follow import FollowReturn, RankingHoldings
from a_domain.rules.trading.ranking import Ranking
from a_domain.rules.trading.ranking_backtest import RankingBacktest
from a_domain.types.enums import Feature, FollowRefusal
from d_presentation.web.routers.backtests import BUSY
from d_presentation.web.routers.runs import STARTED
from d_presentation.web.schemas import Confirmed, ErrorResponse, RunAccepted
from d_presentation.web.session import (
    BacktestTurn,
    CurrentUser,
    NothingToFollow,
    OutsideFollowWindow,
    PrivateAccess,
    QuoteLogin,
    RunStarter,
    UserPipeline,
    WorkflowRunsDependency,
    shows,
)

router = APIRouter(prefix="/rankings", tags=["Rankings"], dependencies=[PrivateAccess, shows(Feature.RANKING)])

UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": (
            "ranking_unavailable: the site's daily history holds no decision session yet; `detail` says what it holds. "
            "backtest_period_unavailable: the period holds no decision session the history holds; `detail` says which "
            "sessions it holds. invalid_request: a query parameter does not validate."
        ),
    }
}


@router.get("/latest", responses=UNAVAILABLE)
async def get_latest_ranking(pipeline: UserPipeline) -> Ranking:
    """
    The monthly stock ranking by revenue acceleration and nearness to the 250-session high at the latest decision session
    the site's daily history holds: the stocks to hold from the next session's open, best first, each with its two
    factors, their ranks and its score, and the revenue month it read. It reads only the held history and the archived
    monthly revenue; a month without revenue ranks nothing and says so in `scored`. The first answer after a start reads
    every held bar, which takes seconds; later ones reuse it until the history holds another session.
    """
    return await pipeline.load_ranking()


@router.get("/backtest", responses=UNAVAILABLE | BUSY, dependencies=[BacktestTurn])
async def get_ranking_backtest(first: date, last: date, pipeline: UserPipeline) -> RankingBacktest:
    """
    The monthly ranking replayed over the decision sessions from `first` to `last`: bought at each next open in equal
    weights, at the site's fee and tax, against ranking.benchmark_id held over the same sessions by its total return.
    It answers the value of both at every session, their total, annual and yearly returns and drawdowns, the costs, and
    each decision's ranking and the stocks it held. It saves nothing, asks no AI and never orders.
    """
    return await pipeline.run_ranking_backtest(first, last)


class RankingFollowResponse(BaseModel):
    """The user's mock account against the ranking's latest decision, and what following the ranking did so far."""

    holdings: RankingHoldings
    refusal: FollowRefusal | None
    """Why a follow may not start now; None when it may."""

    running: bool
    """Whether this server runs a run of the user now: a follow starts once it ends, and one under way changes `holdings`."""

    performance: FollowReturn | None
    """Null while the mock account has not followed the ranking since it opened."""


FOLLOWING: dict[int | str, dict[str, Any]] = {
    **STARTED,
    **UNAVAILABLE,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": (
            "feature_hidden: the site does not show the user the ranking and the mock account. "
            "realtime_quotes_unavailable: the site prices orders on realtime quotes and has no Shioaji login now."
        ),
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": (
            "nothing_to_follow: the mock account holds the ranking already, or the ranking ranks no stock. "
            "outside_follow_window: the site places no order in the market's phase now. "
            "run_in_progress: another run of this user is still running."
        ),
    },
}


@router.get("/follow", responses=UNAVAILABLE, dependencies=[shows(Feature.MOCK_ACCOUNT)])
async def get_ranking_follow(pipeline: UserPipeline, user: CurrentUser, runs: WorkflowRunsDependency) -> RankingFollowResponse:
    """
    The ranking in the user's mock account: which of the latest decision's stocks it holds and lacks, which of its
    holdings left the ranking, whether a follow may start now, and its return since it first followed the ranking
    against ranking.benchmark_id over the same sessions. It records nothing and never orders.
    """
    holdings, refusal = await pipeline.load_ranking_follow()
    return RankingFollowResponse(
        holdings=holdings,
        refusal=refusal,
        running=runs.running(user.user_id) is not None,
        performance=await pipeline.load_ranking_follow_return(),
    )


@router.post(
    "/follow", status_code=status.HTTP_202_ACCEPTED, dependencies=[shows(Feature.MOCK_ACCOUNT), QuoteLogin], responses=FOLLOWING
)
async def follow_ranking(body: Confirmed, pipeline: UserPipeline, user: CurrentUser, start: RunStarter) -> RunAccepted:
    """
    Brings the user's mock account to the ranking's latest decision, as a run of its own: it sells each holding the
    ranking left and buys each ranked stock the account lacks, at an equal weight of the account in whole lots of
    analysis.lot_size, priced as this site prices an order now, through the same order gates and journal as every
    order. It orders on the mock account only. A second follow of a decision the account already holds answers
    nothing_to_follow.
    """
    _, refusal = await pipeline.load_ranking_follow()

    match refusal:
        case FollowRefusal.NOTHING_TO_FOLLOW:
            raise NothingToFollow("The mock account holds this ranking already, or the ranking ranks no stock.")
        case FollowRefusal.OUTSIDE_FOLLOW_WINDOW:
            raise OutsideFollowWindow("This site places no order in the market's phase now. Follow the ranking when its window opens.")
        case None:
            pass

    return RunAccepted(run_id=start(user, lambda follow_id: pipeline.follow_ranking(run_id=follow_id)))
