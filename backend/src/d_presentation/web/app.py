import asyncio
import math
import sys
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from a_domain.types.enums import ErrorCode
from a_domain.types.errors import (
    AiModelNotOffered,
    AlreadySetUpError,
    LastAdministratorError,
    ListingUnavailableError,
    MopsUnavailable,
    PasswordRefused,
    PasswordRequired,
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
from d_presentation.live_runtime import RuntimeSwitch, archive_closes, watch_settings
from d_presentation.web.routers.api_v1 import router as api_v1_router
from d_presentation.web.session import (
    AdministratorsOnly,
    AppRequestRequired,
    MockBrokerOnly,
    NotFound,
    SetupCodeRefused,
    UnknownHost,
    create_setup_code,
)
from d_presentation.web.workflow_runs import RunInProgress, TooManyRuns, WorkflowRuns

DESCRIPTION = """
Runs the stock-agent workflows and reads what they recorded, on the same runtime as the CLI.

Users. Anyone may register (`POST /v1/auth/register`) while registration is open, and signs in with a username or an
email (`POST /v1/auth/sign-in`), which sets the HttpOnly session cookie `stock_agent_session`. Public: sign-in,
registration, the first-time setup, the built-in strategies and market data (`/v1/market`). Signed in: every other
read and write, each on the user's own runs, decisions, orders, watchlist, mock account and saved technical settings.
Administrator: the users (`/v1/admin/users`) and the settings files (`/v1/admin/settings*`). 401 means sign in: the
session is missing, expired or ended. 403 means signed in but not allowed, and never ends the session. Every write
sends the header `X-Requested-With: stock-agent`, and every write but sign-in, sign-out, registration and setup
repeats `"confirm": true` in its body.

Orders. Full Cycle, specific-stock analysis, valuation and market data never order. Buzz and Intraday send orders
through the same gates and trading journal as the CLI, and the API starts them only while the execution provider is
the mock broker (403 otherwise). No endpoint places, cancels or modifies an order by itself, and the API offers no
manual BUY.

Open data. A public site (`audience: public`) uses only the TWSE and TPEX OpenAPI data the server archives: daily
history and the index trend come from that archive, it has no realtime quote, so Buzz and Intraday answer 403
`realtime_quotes_unavailable`, and it trades on the mock broker only. It reads no news site and no MOPS: the AI step
reads the archived material information, the TWSE news naming the stock and its archived financials, a stock with none
of them is decided on its technical score alone, and every valuation endpoint answers 403 `mops_unavailable`. `GET
/v1/market/audience` answers the site's audience and what it allows, so the web app offers only that. `GET
/v1/market/archive-status` says how many sessions the archive holds and how many the built-in strategies need, `GET
/v1/market/stocks/{stock_id}/financials` answers a stock's archived quarters and monthly revenue, and `GET
/v1/market/attribution` names the open data's providers, datasets and license, which a page showing it must credit.

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
    with 413 before anything reads it: FastAPI parses a body before it checks the bearer token.
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

    if request.url.path.startswith("/v1"):
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
    RealBrokerRefused: (status.HTTP_403_FORBIDDEN, ErrorCode.REAL_BROKER_REFUSED),
    MockBrokerOnly: (status.HTTP_403_FORBIDDEN, ErrorCode.MOCK_BROKER_ONLY),
    RealtimeQuotesUnavailable: (status.HTTP_403_FORBIDDEN, ErrorCode.REALTIME_QUOTES_UNAVAILABLE),
    MopsUnavailable: (status.HTTP_403_FORBIDDEN, ErrorCode.MOPS_UNAVAILABLE),
    SettingsFileRefused: (status.HTTP_403_FORBIDDEN, ErrorCode.SETTINGS_FILE_REFUSED),
    PasswordRequired: (status.HTTP_403_FORBIDDEN, ErrorCode.PASSWORD_REQUIRED),
    PasswordRefused: (status.HTTP_403_FORBIDDEN, ErrorCode.PASSWORD_REFUSED),
    NotFound: (status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND),
    SettingsFileMissing: (status.HTTP_404_NOT_FOUND, ErrorCode.SETTINGS_FILE_MISSING),
    AlreadySetUpError: (status.HTTP_409_CONFLICT, ErrorCode.ALREADY_SET_UP),
    UserExistsError: (status.HTTP_409_CONFLICT, ErrorCode.USER_EXISTS),
    LastAdministratorError: (status.HTTP_409_CONFLICT, ErrorCode.LAST_ADMINISTRATOR),
    TechnicalSettingsConflictError: (status.HTTP_409_CONFLICT, ErrorCode.TECHNICAL_SETTINGS_CONFLICT),
    SettingsConflictError: (status.HTTP_409_CONFLICT, ErrorCode.SETTINGS_CONFLICT),
    RunInProgress: (status.HTTP_409_CONFLICT, ErrorCode.RUN_IN_PROGRESS),
    SettingsEditError: (status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.SETTINGS_EDIT_REFUSED),
    AiModelNotOffered: (status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.AI_MODEL_NOT_OFFERED),
    InvalidSettingsError: (status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.SETTINGS_REFUSED),
    SignInThrottled: (status.HTTP_429_TOO_MANY_REQUESTS, ErrorCode.SIGN_IN_THROTTLED),
    TooManyRuns: (status.HTTP_429_TOO_MANY_REQUESTS, ErrorCode.TOO_MANY_RUNS),
    ListingUnavailableError: (status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.LISTING_UNAVAILABLE),
}
"""
The status and the code each refusal a route lets through answers, with its message as the detail: each refusal
names its code here, once. 401 is the only answer that signs the web app out; 403 says signed in, but not allowed;
409 says read again or wait for the run; 429 says later.
"""


type ErrorAnswer = Callable[[Request, Any], Coroutine[Any, Any, Response]]


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
    """A body, path or query that does not validate: FastAPI's list of the fields and why, as `detail`, with a code."""
    content = {"detail": jsonable_encoder(error.errors()), "code": ErrorCode.INVALID_REQUEST}
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


def error_handlers() -> dict[int | type[Exception], ErrorAnswer]:
    """Every error answer the app gives, each with its code: the refusals of ERROR_ANSWERS and FastAPI's own errors."""
    handlers: dict[int | type[Exception], ErrorAnswer] = dict.fromkeys(ERROR_ANSWERS, answer_refusal)
    return handlers | {StarletteHTTPException: answer_http_error, RequestValidationError: answer_invalid_request}


def create_app(open_switch: Callable[[], AbstractAsyncContextManager[RuntimeSwitch]]) -> FastAPI:
    """
    The FastAPI app. Its lifespan opens the process's runtimes through the startup checks the CLI runs, offers the
    first-time setup while no user exists, watches the settings files and archives the open-data closes on a timer. At
    shutdown it stops the watch and the timer, cancels every running workflow while its runtime is open, so its record
    ends as aborted, then closes every runtime.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        async with open_switch() as switch:
            app.state.runtime_switch = switch

            with switch.hold() as opened:
                app.state.workflow_runs = workflow_runs = WorkflowRuns(opened.runtime.logger)
                await offer_first_time_setup(app, opened.runtime)

            watcher = asyncio.get_running_loop().create_task(watch_settings(switch))
            archiver = asyncio.get_running_loop().create_task(archive_closes(switch))

            try:
                yield

            finally:
                watcher.cancel()
                archiver.cancel()
                await workflow_runs.stop()

    app = FastAPI(
        title="TW-Stock-Alpha-Agent", description=DESCRIPTION, version="0.2.0", lifespan=lifespan, exception_handlers=error_handlers()
    )
    app.include_router(api_v1_router)
    app.middleware("http")(add_security_headers)
    return app
