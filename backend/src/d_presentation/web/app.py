import asyncio
import logging
import math
import sys
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from a_domain.types.enums import ErrorCode
from a_domain.types.errors import (
    AiAllowanceSpentError,
    AiModelNotOffered,
    AlreadySetUpError,
    BacktestPeriodUnavailable,
    BriefLimitReached,
    BrokerNotAnswering,
    BrokerServerChanged,
    BrokerUnavailable,
    FeatureHidden,
    FollowAccountChanged,
    FollowBrokerNotOffered,
    FollowTimeNotOffered,
    GoogleConfirmationRequired,
    LastAdministratorError,
    ListingUnavailableError,
    MopsUnavailable,
    PasswordRefused,
    PasswordRequired,
    RankingUnavailable,
    RealBrokerRefused,
    RealtimeQuotesUnavailable,
    RegistrationClosed,
    SettingsConflictError,
    SettingsEditError,
    SettingsFileMissing,
    SettingsFileRefused,
    SignInRefused,
    SignInRequired,
    SignInThrottled,
    TechnicalSettingsConflictError,
    UserExistsError,
)
from b_application.config.settings_loader import InvalidSettingsError
from d_presentation.dependencies import Runtime
from d_presentation.live_runtime import RuntimeSwitch, collect_daily_data, collect_world, watch_settings
from d_presentation.web.backtest_replays import BacktestReplays, TooManyBacktests
from d_presentation.web.routers.api_v1 import router as api_v1_router
from d_presentation.web.scheduled_follows import follow_rankings_on_schedule, settle_orders_on_schedule
from d_presentation.web.session import (
    API_PATH,
    FLOW_PATH,
    STATUS_PATH,
    AdministratorsOnly,
    AppRequestRequired,
    NotFound,
    NothingToFollow,
    NotSimulation,
    OrderingOff,
    OutsideFollowWindow,
    SetupCodeRefused,
    UnknownHost,
    create_setup_code,
)
from d_presentation.web.workflow_runs import RunInProgress, TooManyRuns, WorkflowRuns

DESCRIPTION = """
Runs the stock-agent workflows and reads what they recorded, on the same runtime as the CLI.

Users. Anyone may register (`POST /v1/auth/register`) while registration is open, and signs in with a username or an
email (`POST /v1/auth/sign-in`), which sets the HttpOnly session cookie `stock_agent_session`. A site with a Google
client also signs in with Google: the browser goes to `GET /v1/auth/google/start`, and Google sends it back to `GET
/v1/auth/google/callback`, which sets the same cookie and sends the browser to the app. Public: sign-in,
registration, the first-time setup, the built-in strategies and market data (`/v1/market`). Signed in: every other
read and write, each on the user's own runs, decisions, orders, watchlist, mock account and saved technical settings.
Administrator: the users (`/v1/admin/users`) and the settings form (`/v1/admin/settings`). 401 means sign in: the
session is missing, expired or ended. 403 means signed in but not allowed, and never ends the session. Every write
sends the header `X-Requested-With: stock-agent`, and every write but sign-in, sign-out, registration and setup
repeats `"confirm": true` in its body.

Orders. Full Cycle, specific-stock analysis, valuation and market data never order. Buzz, Intraday and a manual BUY
of a stock a specific-stock run reported (`POST /v1/runs/{run_id}/manual-buy`) send orders through the same gates and
trading journal as the CLI, on the broker their `broker` query names for the whole run: the user's mock account by
default, or SinoPac (`shioaji`) for an administrator while the site's Shioaji login is up, on its simulation server
in dev and test and on the real account in prod, each BUY within trading.max_order_value and the day's within
trading.max_daily_buy_value (`GET /v1/account/brokers` names them). A follow (`POST /v1/runs/{run_id}/follow`) places a
finished Full Cycle's open decisions in the user's mock account only, priced again: at a fresh realtime quote in
continuous trading, or on a site without realtime quotes at the last session's official close while no session
trades. A ranking follow (`POST /v1/rankings/follow`) brings the user's follow account to the monthly ranking's latest
decision, priced the same way: the mock account, or SinoPac's simulation account for an administrator the site lets
order on SinoPac who chose it on My settings, and only there: on a login that is not on SinoPac's simulation server it
answers 403 `not_simulation` and every order of a ranking follow is refused, whatever the settings.
No endpoint cancels or modifies an order.

Open data. A public site (`audience: public`) uses only the TWSE and TPEX OpenAPI data the server archives: daily
history and the index trend come from that archive, it has no realtime quote, so Buzz and Intraday answer 403
`realtime_quotes_unavailable`, and it trades on the mock broker only. A personal site reads its daily history and
index trend from the exchanges' own daily reports; without a Shioaji login it has no realtime quote either, so it
answers Buzz and Intraday the same way. A public site reads no news site and no MOPS: the AI step
reads the archived material information, the TWSE news naming the stock and its archived financials, a stock with none
of them is decided on its technical score alone, and every valuation endpoint answers 403 `mops_unavailable`. `GET
/v1/market/audience` answers the site's audience and what it allows, so the web app offers only that.

Backtests. `POST /v1/backtests` replays the user's active technical strategy over past sessions the site already
holds, with the live trading rules on the technical score alone, and saves the result for the user (`GET
/v1/backtests`, `GET /v1/backtests/{backtest_id}`). `GET /v1/backtests/options` names the period it may cover. A
backtest asks no AI, touches no account, watchlist or run record, and never orders.

Rankings. The settings hold the formulas the ranking can be made by (`ranking.formulas`) and which one is active
(`ranking.active_formula`); a save that switches it applies at once, to the ranking, every stock's score, the backtest
and a follow alike. `GET /v1/rankings/latest` answers the monthly stock ranking by the active formula at the latest
decision session the site's daily history holds, and `GET /v1/rankings/backtest?first=&last=` replays it over a period
against the ranking.benchmark_id held over the same sessions. `GET /v1/rankings/formulas?first=&last=` replays every
formula over the same period and costs, and again at a liquidity floor, as the evidence beside the choice. All read only
the held history and the archived monthly revenue, which `just backfill-history` brings back; they ask no AI, touch no
account and never order. Each user follows the ranking on one follow account, chosen on My settings (`PUT
/v1/rankings/follow/account`): the mock account, or SinoPac's simulation account for an administrator the site lets
order on SinoPac. `GET /v1/rankings/follow` answers that account against the ranking, why a follow may not start there
now, the mock account's return since it first followed against the benchmark, and the user's follows with the account
and the formula each used; `POST /v1/rankings/follow` brings the follow account to the ranking, as a run that orders on
that account only and keeps the formula it used. A ranking follow is refused while the site's SinoPac login is not on
the simulation server, so it never orders with real money, and a follow account the site does not let the user follow
on now is refused, never swapped for the mock account. `PUT /v1/rankings/follow/schedule` lets the user schedule that
follow without changing the account: from the time they choose, on the first session after each new decision, the
server starts the same run by itself, once per decision, on the follow account and on no other, and its record says the
schedule started it. No other run starts without a request.

The server replays `accounts.max_concurrent_backtests` strategy backtests and ranking backtests at once, and one more
waits its turn. A user's request past `accounts.max_backtests_per_user` replaying or waiting answers 429
`too_many_backtests`.

Workflows run in the background, one at a time per user and a few at a time per server: a start answers 202 with the
run id, and GET /v1/runs/{run_id} reports the run's state and its record; another user's run id answers 404. Run the
server with one worker process.
"""

MAX_BODY_BYTES = 2_000_000
"""The largest request body: 50 strategies of 100 rules, or every prompt at its longest, fit well inside it."""

API_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


async def add_security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """
    Marks every API answer private, not framable and not sniffable, and refuses a body larger than MAX_BODY_BYTES
    with 413 before anything reads it: FastAPI parses a body before a route's gates check the session.
    """
    declared = request.headers.get("content-length", "0")

    if "transfer-encoding" in request.headers or not declared.isdigit() or int(declared) > MAX_BODY_BYTES:
        return JSONResponse(
            {
                "detail": f"A request body may hold at most {MAX_BODY_BYTES} bytes, with a Content-Length.",
                "code": ErrorCode.BODY_TOO_LARGE,
            },
            status_code=413,
        )

    response = await call_next(request)

    if request.url.path.startswith(API_PATH):
        response.headers.update(API_SECURITY_HEADERS)

    return response


ERROR_ANSWERS: dict[type[Exception], tuple[int, ErrorCode]] = {
    SignInRequired: (status.HTTP_401_UNAUTHORIZED, ErrorCode.SIGN_IN_REQUIRED),
    SignInRefused: (status.HTTP_401_UNAUTHORIZED, ErrorCode.SIGN_IN_REFUSED),
    UnknownHost: (status.HTTP_400_BAD_REQUEST, ErrorCode.UNKNOWN_HOST),
    AppRequestRequired: (status.HTTP_403_FORBIDDEN, ErrorCode.APP_REQUEST_REQUIRED),
    RegistrationClosed: (status.HTTP_403_FORBIDDEN, ErrorCode.REGISTRATION_CLOSED),
    SetupCodeRefused: (status.HTTP_403_FORBIDDEN, ErrorCode.SETUP_CODE_REFUSED),
    AdministratorsOnly: (status.HTTP_403_FORBIDDEN, ErrorCode.ADMINISTRATORS_ONLY),
    FeatureHidden: (status.HTTP_403_FORBIDDEN, ErrorCode.FEATURE_HIDDEN),
    RealBrokerRefused: (status.HTTP_403_FORBIDDEN, ErrorCode.REAL_BROKER_REFUSED),
    BrokerUnavailable: (status.HTTP_403_FORBIDDEN, ErrorCode.BROKER_UNAVAILABLE),
    NotSimulation: (status.HTTP_403_FORBIDDEN, ErrorCode.NOT_SIMULATION),
    OrderingOff: (status.HTTP_403_FORBIDDEN, ErrorCode.ORDERING_OFF),
    FollowBrokerNotOffered: (status.HTTP_403_FORBIDDEN, ErrorCode.FOLLOW_BROKER_NOT_OFFERED),
    RealtimeQuotesUnavailable: (status.HTTP_403_FORBIDDEN, ErrorCode.REALTIME_QUOTES_UNAVAILABLE),
    MopsUnavailable: (status.HTTP_403_FORBIDDEN, ErrorCode.MOPS_UNAVAILABLE),
    SettingsFileRefused: (status.HTTP_403_FORBIDDEN, ErrorCode.SETTINGS_FILE_REFUSED),
    PasswordRequired: (status.HTTP_403_FORBIDDEN, ErrorCode.PASSWORD_REQUIRED),
    PasswordRefused: (status.HTTP_403_FORBIDDEN, ErrorCode.PASSWORD_REFUSED),
    GoogleConfirmationRequired: (status.HTTP_403_FORBIDDEN, ErrorCode.GOOGLE_CONFIRMATION_REQUIRED),
    NotFound: (status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND),
    SettingsFileMissing: (status.HTTP_404_NOT_FOUND, ErrorCode.SETTINGS_FILE_MISSING),
    AlreadySetUpError: (status.HTTP_409_CONFLICT, ErrorCode.ALREADY_SET_UP),
    UserExistsError: (status.HTTP_409_CONFLICT, ErrorCode.USER_EXISTS),
    LastAdministratorError: (status.HTTP_409_CONFLICT, ErrorCode.LAST_ADMINISTRATOR),
    TechnicalSettingsConflictError: (status.HTTP_409_CONFLICT, ErrorCode.TECHNICAL_SETTINGS_CONFLICT),
    SettingsConflictError: (status.HTTP_409_CONFLICT, ErrorCode.SETTINGS_CONFLICT),
    RunInProgress: (status.HTTP_409_CONFLICT, ErrorCode.RUN_IN_PROGRESS),
    NothingToFollow: (status.HTTP_409_CONFLICT, ErrorCode.NOTHING_TO_FOLLOW),
    OutsideFollowWindow: (status.HTTP_409_CONFLICT, ErrorCode.OUTSIDE_FOLLOW_WINDOW),
    FollowAccountChanged: (status.HTTP_409_CONFLICT, ErrorCode.FOLLOW_ACCOUNT_CHANGED),
    BrokerServerChanged: (status.HTTP_409_CONFLICT, ErrorCode.BROKER_SERVER_CHANGED),
    SettingsEditError: (status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.SETTINGS_EDIT_REFUSED),
    AiModelNotOffered: (status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.AI_MODEL_NOT_OFFERED),
    FollowTimeNotOffered: (status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.FOLLOW_TIME_NOT_OFFERED),
    InvalidSettingsError: (status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.SETTINGS_REFUSED),
    BacktestPeriodUnavailable: (status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.BACKTEST_PERIOD_UNAVAILABLE),
    RankingUnavailable: (status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.RANKING_UNAVAILABLE),
    SignInThrottled: (status.HTTP_429_TOO_MANY_REQUESTS, ErrorCode.SIGN_IN_THROTTLED),
    TooManyRuns: (status.HTTP_429_TOO_MANY_REQUESTS, ErrorCode.TOO_MANY_RUNS),
    TooManyBacktests: (status.HTTP_429_TOO_MANY_REQUESTS, ErrorCode.TOO_MANY_BACKTESTS),
    AiAllowanceSpentError: (status.HTTP_429_TOO_MANY_REQUESTS, ErrorCode.AI_ALLOWANCE_SPENT),
    BriefLimitReached: (status.HTTP_429_TOO_MANY_REQUESTS, ErrorCode.BRIEF_LIMIT_REACHED),
    ListingUnavailableError: (status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.LISTING_UNAVAILABLE),
    BrokerNotAnswering: (status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.BROKER_NOT_ANSWERING),
}
"""
The status and the code each refusal a route lets through answers, with its message as the detail: each refusal
names its code here, once. 401 is the only answer that signs the web app out; 403 says signed in, but not allowed;
409 says read again or wait for the run; 429 says later; 503 says a source did not answer, so ask again.
"""


type ErrorAnswer = Callable[[Request, Any], Coroutine[Any, Any, Response]]


def tidy_access_line(record: logging.LogRecord) -> bool:
    """
    What uvicorn's access log leaves out. The container's health check and every open page ask for the site's status,
    the check every ten seconds, so an answered status request is not logged; one that fails still is. Google's code
    and state arrive in the callback's query, so a request to a Google endpoint is logged by its path alone.
    """
    args = record.args

    if not isinstance(args, tuple) or len(args) != 5:
        return True

    if args[2] == STATUS_PATH and args[4] == status.HTTP_200_OK:
        return False

    if str(args[2]).startswith(FLOW_PATH):
        record.args = (*args[:2], str(args[2]).split("?")[0], *args[3:])

    return True


async def answer_refusal(request: Request, error: Exception) -> JSONResponse:
    """
    `{detail, code}`. A throttled attempt also says, in Retry-After, how many seconds remain. Settings the app would not
    start with also list their problems, each at its file, line and column, never a value.
    """
    status_code, code = ERROR_ANSWERS[type(error)]
    seconds = max(1, math.ceil(error.retry_after.total_seconds())) if isinstance(error, SignInThrottled) else None
    headers = {"Retry-After": str(seconds)} if seconds is not None else None
    content: dict[str, object] = {"detail": str(error), "code": code}

    if isinstance(error, InvalidSettingsError):
        content["problems"] = [asdict(problem) for problem in error.problems]

    return JSONResponse(content, status_code=status_code, headers=headers)


async def answer_http_error(request: Request, error: StarletteHTTPException) -> Response:
    """Every other refusal, such as FastAPI's own 404 for no such route or the LINE webhook's, with a code too."""
    code = ErrorCode.NOT_FOUND if error.status_code == status.HTTP_404_NOT_FOUND else ErrorCode.REQUEST_REFUSED
    return JSONResponse({"detail": error.detail, "code": code}, status_code=error.status_code, headers=error.headers)


async def answer_invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
    """
    A body, path or query that does not validate: each refused field's place, the kind of refusal and why, as `detail`,
    with a code. Never what was sent: FastAPI's own list repeats the input, which can be a password.
    """
    detail = [{"type": problem["type"], "loc": problem["loc"], "msg": problem["msg"]} for problem in error.errors()]
    content = {"detail": detail, "code": ErrorCode.INVALID_REQUEST}
    return JSONResponse(content, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


async def offer_first_time_setup(app: FastAPI, runtime: Runtime) -> None:
    """
    While no user exists, the setup needs a code this start prints on the server's console only, so the first visitor
    of a server reachable from elsewhere cannot make themselves its administrator. The CLI needs none: it runs here.
    """
    options = await runtime.signed_out.load_sign_in_options()
    app.state.setup_code = create_setup_code() if options.needs_first_administrator else None

    if app.state.setup_code is not None:
        print(
            f"No administrator yet. Set one up in the web app with the setup code {app.state.setup_code}, or with `just cli`.",
            file=sys.stderr,
            flush=True,
        )


async def open_app_state(app: FastAPI, switch: RuntimeSwitch) -> WorkflowRuns:
    """
    What the requests read from app.state, set before the first one: the runtimes, the backtests in flight, the
    background runs and the first-time setup's code. An environment that serves the API docs (SystemEnvironment.api_docs)
    gets /docs, /redoc and /openapi.json here, which answer anyone outside the /v1 host check; the app is built without.
    """
    app.state.runtime_switch = switch
    app.state.backtest_replays = BacktestReplays()

    with switch.hold() as opened:
        app.state.workflow_runs = workflow_runs = WorkflowRuns(opened.runtime.logger)
        await offer_first_time_setup(app, opened.runtime)

        if opened.runtime.config.environment.api_docs:
            app.openapi_url = "/openapi.json"
            app.setup()

    return workflow_runs


def error_handlers() -> dict[int | type[Exception], ErrorAnswer]:
    """Every error answer the app gives, each with its code: the refusals of ERROR_ANSWERS and FastAPI's own errors."""
    handlers: dict[int | type[Exception], ErrorAnswer] = dict.fromkeys(ERROR_ANSWERS, answer_refusal)
    return handlers | {StarletteHTTPException: answer_http_error, RequestValidationError: answer_invalid_request}


def start_timers(switch: RuntimeSwitch, workflow_runs: WorkflowRuns) -> list[asyncio.Task[None]]:
    """
    The lifespan's timers, each started: the settings watch, the daily data, the world, the scheduled ranking follows,
    and the settlement of the orders whose outcome a run could not read.
    """
    timers = (
        watch_settings(switch),
        collect_daily_data(switch),
        collect_world(switch),
        follow_rankings_on_schedule(switch, workflow_runs),
        settle_orders_on_schedule(switch),
    )
    return [asyncio.create_task(timer) for timer in timers]


async def stop_timers(timers: Sequence[asyncio.Task[None]]) -> None:
    """Cancels the lifespan's timers and waits until each has ended."""
    for timer in timers:
        timer.cancel()

    await asyncio.gather(*timers, return_exceptions=True)


def create_app(open_switch: Callable[[], AbstractAsyncContextManager[RuntimeSwitch]]) -> FastAPI:
    """
    The FastAPI app. Its lifespan opens the process's runtimes through the startup checks the CLI runs, sets what the
    requests read from app.state, watches the settings files and runs three timers: the daily data (collect_daily_data),
    the world news, indicators and the day's world brief (collect_world), and the scheduled ranking follows that are due
    (follow_rankings_on_schedule). At shutdown it stops the watch and the timers and waits until each has ended, so a
    collection never outlives the runtime it holds, cancels every running workflow while its runtime is open, so its
    record ends as aborted, then closes every runtime.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        async with open_switch() as switch:
            workflow_runs = await open_app_state(app, switch)
            timers = start_timers(switch, workflow_runs)

            try:
                yield

            finally:
                await stop_timers(timers)
                await workflow_runs.stop()

    app = FastAPI(
        title="TW-Stock-Alpha-Agent",
        description=DESCRIPTION,
        version="0.2.0",
        lifespan=lifespan,
        exception_handlers=error_handlers(),
        openapi_url=None,
    )
    app.include_router(api_v1_router)
    app.middleware("http")(add_security_headers)
    logging.getLogger("uvicorn.access").addFilter(tidy_access_line)
    return app
