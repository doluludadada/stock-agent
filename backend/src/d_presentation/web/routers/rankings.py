from datetime import date, datetime, time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict

from a_domain.model.trading.ranking_formula import RankingFormula
from a_domain.rules.trading.follow import FollowAccount, FollowReturn, RankingHoldings
from a_domain.rules.trading.ranking import Ranking
from a_domain.rules.trading.ranking_backtest import RankingBacktest
from a_domain.types.enums import ExecutionProvider, Feature, FollowAccountRefusal, FollowRefusal
from a_domain.types.errors import BrokerUnavailable, FollowAccountChanged
from d_presentation.web.routers.backtests import BUSY
from d_presentation.web.routers.runs import STARTED
from d_presentation.web.schemas import Confirmed, ErrorResponse, PublicText, Response, RunAccepted
from d_presentation.web.session import (
    BacktestTurn,
    CurrentUser,
    NothingToFollow,
    NotSimulation,
    OrderingOff,
    OutsideFollowWindow,
    PrivateAccess,
    QuoteLogin,
    RunStarter,
    RuntimeDependency,
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
    """One ranking follow of the user (its run record) with the formula it used, as the settings defined it then."""

    run_id: UUID
    start_time: datetime
    execution_provider: ExecutionProvider
    """
    The account it ran on: the user's mock account, or SinoPac's simulation account. `GET /v1/runs/{run_id}/orders`
    answers its orders, each with the status the broker gave it.
    """

    ranking_formula: RankingFormula
    ranking_decided_on: date
    """The decision session of the ranking it took."""

    scheduled: bool
    """Whether the user's schedule started it; the user's own click otherwise."""


class UnfinishedFollow(Response):
    """A scheduled ranking follow that left its decision pending (its run record), without the record's own texts but its failure."""

    run_id: UUID
    start_time: datetime
    end_time: datetime | None
    """Null while it runs, and for a run whose process stopped."""

    failure: PublicText | None
    """The exception that stopped it; null when it ran every step."""

    ranking_open: int | None
    """
    How many stocks it still had to trade at its last look at the account: an order was refused or did not fill, or a
    stock got no decision. Null when it took nothing: the account or the market's phase refused it, or the ranking
    ranked no stock.
    """


class FollowScheduleResponse(Response):
    """The user's schedule of the ranking follow (FollowSchedule), its last unfinished follow without the record's own texts."""

    time: time | None
    """The time of day in Taipei from which the site follows by itself, on the follow account. Null: the schedule is off."""

    times: tuple[time, ...]
    """The times the site offers."""

    pending: date | None
    """
    The ranking's latest decision while a session after it has come and no ranking follow of the follow account
    finished it under the active formula, by the schedule or by hand: the schedule follows it on each session it can,
    once a day, until a follow leaves nothing to trade. Null once one did, and while the history holds no decision.
    """

    unfinished: UnfinishedFollow | None
    """The schedule's last follow of `pending` that left it pending. Null while the schedule has not tried."""

    due: bool
    """The schedule follows `pending` now: it is on, its time has come today, and the market is in the phase orders are placed in."""


class RankingFollowResponse(BaseModel):
    """The user's follow account against the ranking's latest decision, and what following the ranking did so far."""

    account: FollowAccount
    """
    The user's follow account, the accounts the site offers them as one now, and why a follow may not order on it now
    (`account.refusal`, the same code `POST /v1/rankings/follow` answers then), which leaves the account unread.
    """

    holdings: RankingHoldings
    """
    The ranking in the follow account: the mock account's book, or SinoPac's positions as the broker lists them. Empty
    while `account.refusal` says the site does not offer the user the account now.
    """

    refusal: FollowRefusal | None
    """
    Why a follow may not start on the follow account now, for its holdings or the market's phase; None when it may,
    and while `account.refusal` refuses the account.
    """

    running: bool
    """Whether this server runs a run of the user now: a follow starts once it ends, and one under way changes `holdings`."""

    performance: FollowReturn | None
    """
    The mock account's return since it first followed the ranking, against the benchmark. Null while it never did, and
    while the follow account is SinoPac, whose history the site does not keep, or is refused.
    """

    follows: list[RankingFollowRun]
    """
    The user's ranking follows that took a decision, on the mock account since it opened and on SinoPac, oldest first,
    each with its account, the formula it used and who started it: `performance` is what all of the mock account's
    made together, never one formula's result when several are listed.
    """

    schedule: FollowScheduleResponse
    """The user's schedule of the follow: its time, the decision it still has to follow, and whether it follows it now."""


class FollowSettingsResponse(BaseModel):
    """My settings' ranking follow: the user's follow account and their schedule of the follow there."""

    account: FollowAccount
    schedule: FollowScheduleResponse


FOLLOWING: dict[int | str, dict[str, Any]] = {
    **STARTED,
    **UNAVAILABLE,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": (
            "ordering_off, not_simulation, broker_unavailable: the user's follow account refuses a ranking follow now "
            "(FollowAccountRefusal, `account.refusal` of `GET /v1/rankings/follow`). realtime_quotes_unavailable: the "
            "site prices orders on realtime quotes and has no Shioaji login now. None of these follows on another account."
        ),
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": (
            "follow_account_changed: `broker` is not the user's follow account as saved now. "
            "nothing_to_follow: the account holds the ranking already, or the ranking ranks no stock. "
            "outside_follow_window: the site places no order in the market's phase now. "
            "run_in_progress: another run of this user is still running."
        ),
    },
}


@router.get("/follow", responses=UNAVAILABLE)
async def get_ranking_follow(pipeline: UserPipeline, user: CurrentUser, runs: WorkflowRunsDependency) -> RankingFollowResponse:
    """
    The ranking in the user's follow account (`account`): which of the latest decision's stocks it holds and lacks,
    which of its holdings left the ranking (every holding while the active formula holds cash), whether a follow may
    start now and why not, the mock account's return since it first followed the ranking against ranking.benchmark_id
    over the same sessions, the user's follows so far, on that account and on SinoPac, with the account and the
    formula each used and whether the schedule or the user started it, and the user's schedule. It reads the account,
    SinoPac's positions in one request, only while the site offers it to the user; it records nothing and never orders.
    """
    account, schedule, holdings, refusal, performance, follows = await pipeline.load_ranking_follow(user)
    return RankingFollowResponse(
        account=account,
        holdings=holdings,
        refusal=refusal,
        running=runs.running(user.user_id) is not None,
        performance=performance,
        follows=[RankingFollowRun.model_validate(run) for run in follows],
        schedule=FollowScheduleResponse.model_validate(schedule),
    )


@router.get("/follow/schedule")
async def get_follow_schedule(pipeline: UserPipeline, user: CurrentUser) -> FollowSettingsResponse:
    """
    My settings: the user's follow account, the accounts the site offers them as one now and why it refuses theirs,
    and their schedule of the ranking follow as it stands, with the times the site offers. It answers on a site that
    can make no ranking yet, where nothing is pending. It reads no account, records nothing and never orders.
    """
    settings = await pipeline.load_follow_schedule(user)
    return FollowSettingsResponse(account=settings.account, schedule=FollowScheduleResponse.model_validate(settings.schedule))


class FollowAccountRequest(Confirmed):
    model_config = ConfigDict(extra="forbid")

    broker: ExecutionProvider
    """One of the accounts the site offers the user as their follow account now (`account.brokers`)."""


NOT_OFFERED: dict[int | str, dict[str, Any]] = {
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": (
            "follow_broker_not_offered: the site does not offer the user that account as their follow account now, "
            "and a new account or a schedule that is on needs one it offers; nothing saved."
        ),
    }
}


@router.put("/follow/account", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_OFFERED)
async def choose_follow_account(body: FollowAccountRequest, pipeline: UserPipeline, user: CurrentUser) -> None:
    """
    My settings: the user's follow account, one of those the site offers them now. The schedule's time stays as it
    is, and follows on the new account.
    """
    await pipeline.choose_ranking_follow(user, user.ranking_follow_time, body.broker)


class FollowScheduleRequest(Confirmed):
    model_config = ConfigDict(extra="forbid")

    time: time | None
    """One of the times the schedule offers (`times`), or null for no schedule."""


@router.put(
    "/follow/schedule",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_OFFERED
    | {
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "follow_time_not_offered: the site does not offer that time; nothing saved.",
        }
    },
)
async def schedule_ranking_follow(body: FollowScheduleRequest, pipeline: UserPipeline, user: CurrentUser) -> None:
    """
    My settings: schedules the user's ranking follow on their follow account, or turns the schedule off with null; the
    account stays as it is. With a time, the site follows each new decision of the ranking into that account by itself
    on the first session after it, from that time in Taipei and while this site places orders, as a run like the
    button's (`POST /v1/rankings/follow`): the same account, sizing, order gates and journal, recorded as started by
    the schedule. A decision counts as finished on the account its follow ran on. It follows a decision until a follow
    left the account nothing to trade for it under the active formula, and never one the user finished by hand; a day
    whose window it missed, or whose follow ordered nothing or only a part, is tried again on the next session, once a
    day, until the next decision supersedes it. Setting a time needs an account the site offers; turning the schedule
    off does not. While the site does not offer the account, the schedule follows on no account, and on no other.
    """
    await pipeline.choose_ranking_follow(user, body.time, user.ranking_follow_broker)


class FollowRankingRequest(Confirmed):
    model_config = ConfigDict(extra="forbid")

    broker: ExecutionProvider
    """The follow account the user confirmed (`account.broker`): one that is no longer theirs answers follow_account_changed."""


def refuse_ranking_follow(account: FollowAccount, refusal: FollowRefusal | None, broker: ExecutionProvider) -> None:
    """409 for a follow that names another account than the user's follow account, then the refusal's own code."""
    if broker != account.broker:
        raise FollowAccountChanged(f"Your follow account is {account.broker.label} now, not {broker.label}. Nothing started.")

    match account.refusal:
        case FollowAccountRefusal.ORDERING_OFF:
            raise OrderingOff(f"This site does not let your ranking follow order on {broker.label} now.")
        case FollowAccountRefusal.NOT_SIMULATION:
            raise NotSimulation(
                "A ranking follow orders on a real broker's simulation server only, and this site's login is not on it."
            )
        case FollowAccountRefusal.BROKER_UNAVAILABLE:
            raise BrokerUnavailable(f"This site has no {broker.label} login your ranking follow may order on now.")
        case None:
            pass

    match refusal:
        case FollowRefusal.NOTHING_TO_FOLLOW:
            raise NothingToFollow("The account holds this ranking already, or the ranking ranks no stock.")
        case FollowRefusal.OUTSIDE_FOLLOW_WINDOW:
            raise OutsideFollowWindow("This site places no order in the market's phase now. Follow the ranking when its window opens.")
        case None:
            return


@router.post("/follow", status_code=status.HTTP_202_ACCEPTED, dependencies=[QuoteLogin], responses=FOLLOWING)
async def follow_ranking(
    body: FollowRankingRequest, pipeline: UserPipeline, runtime: RuntimeDependency, user: CurrentUser, start: RunStarter
) -> RunAccepted:
    """
    Brings the user's follow account, the one `broker` names as the user confirmed it, to the ranking's latest
    decision by the active formula, as a run of its own on that account and no other, which keeps that formula: it
    sells each holding the ranking left and buys each ranked stock the account lacks, at an equal weight of the account
    in whole lots of analysis.lot_size, priced as this site prices an order now, through the same order gates and
    journal as every order. While the formula holds cash it sells every holding and buys nothing. A second follow of a
    decision the account already holds answers nothing_to_follow. On SinoPac it follows into the simulation account,
    each BUY sized inside trading.max_order_value and refused past trading.max_daily_buy_value. SinoPac pays a sale at
    settlement, so there a follow buys only what the cash the account has now pays for whole, best first, and the
    run's log names each BUY that waits for a later follow. The order gates refuse each order of a ranking follow on a
    login that is not on SinoPac's simulation server again. A ranking follow never orders with real money.
    """
    account, _, _, refusal, _, _ = await pipeline.load_ranking_follow(user)
    refuse_ranking_follow(account, refusal, body.broker)
    follow = runtime.pipeline_for(user, body.broker)

    return RunAccepted(run_id=start(user, lambda follow_id: follow.follow_ranking(user, run_id=follow_id)))
