"""
Who a Web request is and what it may reach: the session cookie, the CSRF header, the allowed host names, the one-time
setup code and the gates of the private and the administrator routes. Every gate is a router or route dependency, so
a route's decorator or its router shows what it requires; none is a side effect of building a Pipeline.
"""

import secrets
from collections.abc import AsyncGenerator, Awaitable, Callable
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, Request, Response
from fastapi.security import APIKeyCookie
from pydantic import SecretStr

from a_domain.model.system.user import User, UserSession
from a_domain.types.enums import ExecutionProvider, Permission
from a_domain.types.errors import MopsUnavailable, RealBrokerRefused, RealtimeQuotesUnavailable, SignInRequired
from a_domain.types.ids import RunId, SessionToken
from b_application.pipeline import Pipeline
from b_application.schemas.pipeline_status import PipelineStatus
from d_presentation.dependencies import Runtime
from d_presentation.live_runtime import OpenedRuntime, RuntimeSwitch
from d_presentation.web.market_valuation_cache import MarketValuationCache
from d_presentation.web.workflow_runs import WorkflowRuns

SESSION_COOKIE = "stock_agent_session"
APP_REQUEST_HEADER = "X-Requested-With"
APP_REQUEST_VALUE = "stock-agent"

session_cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    auto_error=False,
    description="The session POST /v1/auth/sign-in sets: HttpOnly, SameSite=Strict, Path=/v1, Secure over https.",
)

SessionCookie = Annotated[str | None, Depends(session_cookie)]


class UnknownHost(Exception):
    """The Host header names none of api.allowed_hosts. 400."""


class AppRequestRequired(PermissionError):
    """A write without the web app's X-Requested-With header (CSRF). 403."""


class AdministratorsOnly(PermissionError):
    """A signed-in user without the permission the route needs. 403: the session stays."""


class MockBrokerOnly(PermissionError):
    """Buzz or Intraday on an installation whose broker is not the mock. 403."""


class SetupCodeRefused(PermissionError):
    """The first-time setup with a code this server did not print. 403."""


class NotFound(LookupError):
    """Nothing of that id that this user may see. 404, said in words."""


def get_runtime_switch(request: Request) -> RuntimeSwitch:
    """The process's one switch, which the app's lifespan opened. The only reader of the runtimes in app.state."""
    return request.app.state.runtime_switch


RuntimeSwitchDependency = Annotated[RuntimeSwitch, Depends(get_runtime_switch)]


async def request_hold(switch: RuntimeSwitchDependency) -> AsyncGenerator[OpenedRuntime]:
    """
    The runtime this request runs on, held from its first dependency to its answer. FastAPI solves a dependency once
    per request, so the host check, the session, the gates and the route all read one runtime, whatever a reload does
    meanwhile, and the Pipeline a run gets comes from the runtime its gates read.
    """
    with switch.hold() as opened:
        yield opened


RequestHold = Annotated[OpenedRuntime, Depends(request_hold)]


def get_runtime(opened: RequestHold) -> Runtime:
    return opened.runtime


RuntimeDependency = Annotated[Runtime, Depends(get_runtime)]


def get_market_valuation_cache(runtime: RuntimeDependency) -> MarketValuationCache:
    return runtime.market_valuation_cache


MarketValuationDependency = Annotated[MarketValuationCache, Depends(get_market_valuation_cache)]


def get_workflow_runs(request: Request) -> WorkflowRuns:
    """The server's background runs, which the app's lifespan created."""
    return request.app.state.workflow_runs


WorkflowRunsDependency = Annotated[WorkflowRuns, Depends(get_workflow_runs)]

type Workflow = Callable[[RunId], Awaitable[PipelineStatus]]
type RunStart = Callable[[User, Workflow], RunId]


def run_starter(opened: RequestHold, runs: WorkflowRunsDependency) -> RunStart:
    """
    Starts a background run on the runtime this request holds, the one its Pipeline and its gates came from; the run
    holds that runtime until it ends. 409 (RunInProgress) while the user's run runs; 429 (TooManyRuns) while the server
    runs that runtime's accounts.max_concurrent_runs, never for an administrator.
    """
    cap = opened.runtime.config.accounts.max_concurrent_runs
    return lambda user, workflow: runs.start(user, opened.hold(), workflow, cap)


RunStarter = Annotated[RunStart, Depends(run_starter)]


def require_known_host(request: Request, runtime: RuntimeDependency) -> None:
    """
    Every /v1 request: 400 unless its Host header names one of api.allowed_hosts, so a page on another site cannot
    reach the API through DNS rebinding.
    """
    if request.url.hostname not in runtime.config.api.allowed_hosts:
        raise UnknownHost("Unknown host.")


def require_app_request(request: Request) -> None:
    """
    CSRF: every /v1 write must carry X-Requested-With: stock-agent. A page on another site cannot add that header
    without a CORS preflight, which this API never grants, and the session cookie is SameSite=Strict too. The LINE
    webhook's router does not get this dependency: LINE signs its calls instead.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    if request.headers.get(APP_REQUEST_HEADER) != APP_REQUEST_VALUE:
        raise AppRequestRequired(f"A write needs the header {APP_REQUEST_HEADER}: {APP_REQUEST_VALUE}.")


def require_mock_broker(runtime: RuntimeDependency) -> None:
    """
    Buzz and Intraday send orders. The Web API starts them only on the mock broker, so a browser never reaches a
    real account: 403 for any other execution provider, whatever the order mode.
    """
    if runtime.config.trading.execution_provider != ExecutionProvider.MOCK:
        raise MockBrokerOnly(
            "The Web API starts Buzz and Intraday only on the mock broker. Use the CLI for another execution provider."
        )


def require_realtime_quotes(runtime: RuntimeDependency) -> None:
    """
    Buzz and Intraday order on realtime quotes. A deployment on open data only (audience public) has none, so it
    refuses them with 403 before any run starts.
    """
    if not runtime.config.audience.realtime_quotes:
        raise RealtimeQuotesUnavailable(
            "This site uses open data only, which has no realtime quotes, so it cannot run Buzz or Intraday: both order on one."
        )


def require_mops(runtime: RuntimeDependency) -> None:
    """
    The valuation reads MOPS's income statements. A deployment on open data only (audience public) reads none, so it
    refuses every valuation endpoint with 403 before anything is loaded.
    """
    if not runtime.config.audience.mops:
        raise MopsUnavailable("This site uses open data only and reads no MOPS income statement, so it offers no valuation.")


async def current_user(runtime: RuntimeDependency, token: SessionCookie) -> User:
    """
    The user of the request's session cookie, read now: 401 when the cookie is missing, unknown or expired, or its
    user was deactivated. 401 is the only answer that makes the web app forget the session. FastAPI reads it once per
    request, however many of the request's dependencies ask for it.
    """
    user = await runtime.signed_out.find_signed_in_user(SessionToken(token)) if token else None

    if user is None:
        raise SignInRequired("Sign in first.")

    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_private_access(runtime: RuntimeDependency, user: CurrentUser) -> None:
    """
    Every private route: a signed-in user, and on an installation whose broker is real, one with USE_REAL_BROKER. A
    user without it gets 403, signed in still, before any Pipeline of theirs is built: every private page shows or
    trades the one real account.
    """
    if runtime.config.trading.execution_provider != ExecutionProvider.MOCK and Permission.USE_REAL_BROKER not in user.permissions:
        raise RealBrokerRefused("This installation trades on a real broker. Only an administrator may use its private pages.")


def requires(permission: Permission) -> Callable[[User], None]:
    """A route that needs a permission beyond signing in: 403 without it. 403 never signs anyone out."""

    def check(user: CurrentUser) -> None:
        if permission not in user.permissions:
            raise AdministratorsOnly("Administrators only.")

    return check


def user_pipeline(runtime: RuntimeDependency, user: CurrentUser) -> Pipeline:
    """The signed-in user's own Pipeline. Its routes also carry PrivateAccess, which runs first."""
    return runtime.pipeline_for(user)


def signed_out_pipeline(runtime: RuntimeDependency) -> Pipeline:
    """The public routes and the LINE webhook. Its ports that hold users' data refuse, so it reads nobody's data."""
    return runtime.signed_out


UserPipeline = Annotated[Pipeline, Depends(user_pipeline)]
SignedOutPipeline = Annotated[Pipeline, Depends(signed_out_pipeline)]


def set_session_cookie(request: Request, response: Response, session: UserSession) -> None:
    """
    HttpOnly, SameSite=Strict, Path=/v1, for the session's lifetime as a Max-Age, so a client whose clock differs
    keeps it as long; Secure when the request came over https, so plain http on the loopback address works in every
    browser. The server ends the session at its expiry whatever the cookie.
    """
    response.set_cookie(
        SESSION_COOKIE,
        session.token,
        max_age=int((session.expires_at - session.created_at).total_seconds()),
        path="/v1",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/v1", secure=request.url.scheme == "https", httponly=True, samesite="strict")


def client_of(request: Request) -> str:
    """The address the attempt limits count by. Behind a reverse proxy, uvicorn's --proxy-headers makes it the visitor's."""
    return request.client.host if request.client else "unknown"


def host_of(request: Request) -> str:
    """The host name the request reached the API at, one of api.allowed_hosts: require_known_host refused any other."""
    return request.url.hostname or ""


def create_setup_code() -> str:
    """The one-time code the first-time setup needs on the Web: printed on the server's console, made anew at each start."""
    return secrets.token_urlsafe(9)


def check_setup_code(request: Request, code: SecretStr) -> None:
    """403 unless `code` is the code this server printed at its start; compared in constant time."""
    expected = request.app.state.setup_code

    if expected is None or not compare_digest(code.get_secret_value().encode(), expected.encode()):
        raise SetupCodeRefused("Wrong setup code. The server printed it on its console when it started.")


KnownHost = Depends(require_known_host)
AppRequest = Depends(require_app_request)
MockBroker = Depends(require_mock_broker)
RealtimeQuotes = Depends(require_realtime_quotes)
Mops = Depends(require_mops)
PrivateAccess = Depends(require_private_access)
ManageUsers = Depends(requires(Permission.MANAGE_USERS))
EditSystemSettings = Depends(requires(Permission.EDIT_SYSTEM_SETTINGS))
