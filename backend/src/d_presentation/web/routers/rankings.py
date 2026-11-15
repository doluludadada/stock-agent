from datetime import date, datetime, time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel

from a_domain.model.trading.ranking_formula import RankingFormula
from a_domain.rules.trading.follow import FollowReturn, FollowSchedule, RankingHoldings
from a_domain.rules.trading.ranking import Ranking
from a_domain.rules.trading.ranking_backtest import RankingBacktest
from a_domain.types.enums import Feature, FollowRefusal
from d_presentation.web.routers.backtests import BUSY
from d_presentation.web.routers.runs import STARTED
from d_presentation.web.schemas import Confirmed, ErrorResponse, Response, RunAccepted
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
    The monthly stock ranking by the active formula (ranking.active_formula, `formula` in the answer) at the latest
    decision session the site's daily history holds: the stocks to hold from the next session's open, best first, each
    with the formula's factors in order, their ranks and its score, and the revenue month it read. While the formula's
    market filter is on, `holds_cash` is true and it holds no stock. It reads only the held history and the archived
    monthly revenue; a month without revenue ranks nothing and says so in `scored`. The first answer after a start reads
    every held bar, which takes seconds; later ones reuse it until the history holds another session, whatever
    formula is active by then.
    """
    return await pipeline.load_ranking()


@router.get("/backtest", responses=UNAVAILABLE | BUSY, dependencies=[BacktestTurn])
async def get_ranking_backtest(first: date, last: date, pipeline: UserPipeline) -> RankingBacktest:
    """
    The active formula's ranking replayed over the decision sessions from `first` to `last`: bought at each next open
    in equal weights, at the site's fee and tax, against ranking.benchmark_id held over the same sessions by its total
    return. It answers the value of both at every session, their total, annual and yearly returns and drawdowns, the
    costs, the turnover, and each decision's ranking and the stocks it held; a decision at which the formula held cash
    holds none. It saves nothing, asks no AI and never orders.
    """
    return await pipeline.run_ranking_backtest(first, last)


class FormulaRecord(Response):
    """One simulated replay of a formula (RankingBacktest) as the comparison shows it, without its curves and rankings."""

    benchmark_id: str
    annual_return: float | None
    benchmark_annual_return: float | None
    max_drawdown: float
    benchmark_max_drawdown: float | None
    years_ahead: int | None
    """The calendar years it returned more than the benchmark, of the len(yearly_returns) the replay holds."""

    yearly_returns: dict[int, float]
    turnover: float | None
    """The share of the portfolio bought at a rebalance, on average."""


class FormulaEvidence(BaseModel):
    """One formula of ranking.formulas with what holding it would have done over the period. Every figure is simulated."""

    formula: RankingFormula
    active: bool
    """Whether it is ranking.active_formula, the one the ranking, the scores and a follow use now."""

    record: FormulaRecord
    liquid_floor: float
    liquid_record: FormulaRecord
    """The same replay with `liquid_floor`, ranking.evidence_min_traded_value, in place of the formula's min_traded_value."""


@router.get("/formulas", responses=UNAVAILABLE | BUSY, dependencies=[BacktestTurn])
async def get_ranking_formulas(first: date, last: date, pipeline: UserPipeline) -> list[FormulaEvidence]:
    """
    The evidence beside the choice of a formula: every formula of ranking.formulas replayed over the decision sessions
    from `first` to `last` on the same history, fee and tax, in the settings' order, and again at the liquidity floor
    ranking.evidence_min_traded_value. Each row answers the annual return against the benchmark's, the deepest
    drawdown, the years ahead of the benchmark and the turnover. The replays run one after another inside one of the
    server's replay turns, and each is kept while the history stands. A formula that did best over a past period is not
    thereby the best over the next. It saves nothing, asks no AI and never orders.
    """
    active, evidence = await pipeline.compare_ranking_formulas(first, last)
    return [
        FormulaEvidence(
            formula=record.formula,
            active=record.formula.name == active,
            record=FormulaRecord.model_validate(record),
            liquid_floor=liquid.formula.min_traded_value,
            liquid_record=FormulaRecord.model_validate(liquid),
        )
        for record, liquid in evidence
    ]


class RankingFollowRun(Response):
    """One ranking follow of the mock account (its run record) with the formula it used, as the settings defined it then."""

    run_id: UUID
    start_time: datetime
    ranking_formula: RankingFormula
    ranking_decided_on: date
    """The decision session of the ranking it took."""

    scheduled: bool
    """Whether the user's schedule started it; the user's own click otherwise."""


class RankingFollowResponse(BaseModel):
    """The user's mock account against the ranking's latest decision, and what following the ranking did so far."""

    holdings: RankingHoldings
    refusal: FollowRefusal | None
    """Why a follow may not start now; None when it may."""

    running: bool
    """Whether this server runs a run of the user now: a follow starts once it ends, and one under way changes `holdings`."""

    performance: FollowReturn | None
    """Null while the mock account has not followed the ranking since it opened."""

    follows: list[RankingFollowRun]
    """
    The account's ranking follows since it opened that took a decision, oldest first, each with the formula it used
    and who started it: `performance` is what all of them made together, never one formula's result when several are
    listed.
    """

    schedule: FollowSchedule
    """The user's schedule of the follow: its time, the decision it still has to follow, and whether it follows it now."""


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
    holdings left the ranking (every holding while the active formula holds cash), whether a follow may start now, its
    return since it first followed the ranking against ranking.benchmark_id over the same sessions, its follows so
    far with the formula each used and whether the schedule or the user started it, and the user's schedule. It
    records nothing and never orders.
    """
    holdings, refusal = await pipeline.load_ranking_follow()
    performance, follows = await pipeline.load_ranking_follow_return()
    return RankingFollowResponse(
        holdings=holdings,
        refusal=refusal,
        running=runs.running(user.user_id) is not None,
        performance=performance,
        follows=[RankingFollowRun.model_validate(run) for run in follows],
        schedule=await pipeline.load_follow_schedule(user),
    )


class FollowScheduleRequest(Confirmed):
    time: time | None
    """One of the times the schedule offers (`schedule.times`), or null for no schedule."""


@router.put(
    "/follow/schedule",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[shows(Feature.MOCK_ACCOUNT)],
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "follow_time_not_offered: the site does not offer that time; nothing saved.",
        }
    },
)
async def schedule_ranking_follow(body: FollowScheduleRequest, pipeline: UserPipeline, user: CurrentUser) -> None:
    """
    My settings: schedules the user's ranking follow, or turns the schedule off with null. With a time, the site follows
    each new decision of the ranking into the user's mock account by itself on the first session after it, from that
    time in Taipei and while this site places orders, as a run like the button's (`POST /v1/rankings/follow`): the
    same sizing, order gates and journal, on the mock account only, recorded as started by the schedule. It follows a
    decision once, and never one the user followed by hand; a day whose window it missed is tried again on the next
    session until the next decision supersedes it. A user the site hides the ranking or the mock account from, or a
    deactivated one, is followed for by nobody. `GET /v1/rankings/follow` answers the schedule as it stands.
    """
    await pipeline.choose_follow_time(user, body.time)


@router.post(
    "/follow", status_code=status.HTTP_202_ACCEPTED, dependencies=[shows(Feature.MOCK_ACCOUNT), QuoteLogin], responses=FOLLOWING
)
async def follow_ranking(body: Confirmed, pipeline: UserPipeline, user: CurrentUser, start: RunStarter) -> RunAccepted:
    """
    Brings the user's mock account to the ranking's latest decision by the active formula, as a run of its own, which
    keeps that formula: it sells each holding the ranking left and buys each ranked stock the account lacks, at an
    equal weight of the account in whole lots of analysis.lot_size, priced as this site prices an order now, through
    the same order gates and journal as every order. While the formula holds cash it sells every holding and buys
    nothing. It orders on the mock account only. A second follow of a decision the account already holds answers
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
