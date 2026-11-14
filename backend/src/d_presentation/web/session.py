"""
Who a Web request is and what it may reach: the session cookie, the cookie of a sign-in with Google under way, the
CSRF header, the allowed host names, the one-time setup code and the gates of the private and the administrator
routes. Every gate is a router or route dependency, so a route's decorator or its router shows what it requires; none
is a side effect of building a Pipeline.
"""

import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import AsyncGenerator, Awaitable, Callable
from secrets import compare_digest
from typing import Annotated, Any

from fastapi import Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import APIKeyCookie
from pydantic import SecretStr, TypeAdapter

from a_domain.model.system.user import SignInFlow, User, UserSession
from a_domain.types.enums import ExecutionProvider, Feature, FeatureVisibility, HoldingSource, Permission
from a_domain.types.errors import MopsUnavailable, RealtimeQuotesUnavailable, SignInRequired
from a_domain.types.ids import RunId, SessionToken
from b_application.pipeline import Pipeline
from b_application.schemas.pipeline_status import PipelineStatus
from d_presentation.dependencies import Runtime
from d_presentation.live_runtime import OpenedRuntime, RuntimeSwitch
from d_presentation.web.backtest_replays import BacktestReplays
from d_presentation.web.market_valuation_cache import MarketValuationCache
from d_presentation.web.workflow_runs import WorkflowRuns

API_PATH = "/v1"
"""Where every route lives, and the only path the browser sends the session cookie to."""
SESSION_COOKIE = "stock_agent_session"
APP_REQUEST_HEADER = "X-Requested-With"
APP_REQUEST_VALUE = "stock-agent"

FLOW_COOKIE = "stock_agent_google_flow"
FLOW_PATH = f"{API_PATH}/auth/google"
FLOW_JSON = TypeAdapter(SignInFlow)
APP_HOME = "/"
APP_SIGN_IN = "/sign-in"
APP_SETTINGS = "/admin/settings"
"""The web app's pages a Google endpoint sends the browser back to: paths of frontend/src/shared/config/paths.ts."""
CONFIRMED = "confirmed"
THROTTLED = "throttled"
"""What ?google= says on the way back beside a GoogleRefusal: a settings confirmation granted, and the limit per address."""

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


class FeatureHidden(PermissionError):
    """The site does not show the route's feature to this viewer (features.* in appsetting.yaml). 403: the session stays."""


class NothingToFollow(Exception):
    """FollowRefusal.NOTHING_TO_FOLLOW: no decision of the run is left to follow. 409."""


class OutsideFollowWindow(Exception):
    """FollowRefusal.OUTSIDE_FOLLOW_WINDOW: the site places no order in the market's phase now. 409."""


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


def require_realtime_quotes(runtime: RuntimeDependency) -> None:
    """
    Buzz and Intraday order on realtime quotes. A deployment on open data only (audience public) has none, so it
    refuses them with 403 before any run starts, and a personal site refuses them while it has no login (require_quote_login).
    """
    if not runtime.config.audience.realtime_quotes:
        raise RealtimeQuotesUnavailable(
            "This site uses open data only, which has no realtime quotes, so it cannot run Buzz or Intraday: both order on one."
        )

    require_quote_login(runtime)


def require_quote_login(runtime: RuntimeDependency) -> None:
    """
    A site that prices its orders on realtime quotes (personal) needs its Shioaji login for them. Without the key pair,
    or while the login is down, every such order could only be refused as STALE_PRICE, so Buzz, Intraday and a follow
    are refused with 403 before any run starts. A site that prices orders at the official close (public) needs none.
    """
    if runtime.config.audience.realtime_quotes and not runtime.realtime_quotes:
        raise RealtimeQuotesUnavailable(
            "This site has no Shioaji login now, so it has no realtime quote to price an order on. Without the environment's "
            "Shioaji key pair, set it and restart; a login that went down is made again at the next daily data collection."
        )


def require_mops(runtime: RuntimeDependency) -> None:
    """
    The valuation reads MOPS's income statements. A deployment on open data only (audience public) reads none, so it
    refuses every valuation endpoint with 403 before anything is loaded.
    """
    if not runtime.config.audience.mops:
        raise MopsUnavailable("This site uses open data only and reads no MOPS income statement, so it offers no valuation.")


async def viewer(runtime: RuntimeDependency, token: SessionCookie) -> User | None:
    """
    The user of the request's session cookie, read now, or None for a visitor: the cookie is missing, unknown or
    expired, or its user was deactivated. FastAPI reads it once per request, however many of the request's
    dependencies ask for it.
    """
    return await runtime.signed_out.find_signed_in_user(SessionToken(token)) if token else None


Viewer = Annotated[User | None, Depends(viewer)]


async def current_user(user: Viewer) -> User:
    """The signed-in user: 401 for a visitor. 401 is the only answer that makes the web app forget the session."""
    if user is None:
        raise SignInRequired("Sign in first.")

    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_shown(runtime: Runtime, user: User | None, features: tuple[Feature, ...]) -> None:
    """403 (FeatureHidden) unless the runtime's settings show the viewer one of `features`; a visitor has no permission."""
    if shown_features(runtime, user).isdisjoint(features):
        raise FeatureHidden("This site does not show this feature to you.")


def shown_features(runtime: Runtime, user: User | None) -> frozenset[Feature]:
    return runtime.config.features.shown(user.permissions if user else frozenset())


def feature_visibilities(runtime: Runtime) -> dict[Feature, FeatureVisibility]:
    """Whom the site shows each feature to, for the web app's first question: it hides what the server would refuse."""
    return {feature: runtime.config.features.visibility(feature) for feature in Feature}


def shows(*features: Feature) -> Any:
    """
    A route or a router of these features: 403 unless features.* shows the viewer one of them. It is one more gate and
    replaces none: a private route still needs the sign-in, and an order every check of its broker.
    """

    def check(runtime: RuntimeDependency, user: Viewer) -> None:
        require_shown(runtime, user, features)

    return Depends(check)


def require_account_shown(runtime: RuntimeDependency, user: Viewer, broker: ExecutionProvider = ExecutionProvider.MOCK) -> None:
    """A route that reads the account of the `broker` the query names: 403 unless the site shows the viewer that account's feature."""
    require_shown(runtime, user, (broker.account_feature,))


def require_ordering_shown(runtime: RuntimeDependency, user: Viewer, broker: ExecutionProvider = ExecutionProvider.MOCK) -> None:
    """
    A route that orders on the `broker` the query names: 403 unless the site shows the viewer that broker's ordering
    feature. BrokerAccessRule checks the same again at each send, so the refusal never rests on this route alone.
    """
    require_shown(runtime, user, (broker.ordering_feature,))


def holding_sources(runtime: RuntimeDependency, user: CurrentUser) -> frozenset[HoldingSource]:
    """
    The sources the My holdings page may read for the user: those whose feature the site shows the user and whose
    permission, where reading one needs it, the user has.
    """
    shown = shown_features(runtime, user)
    return frozenset(
        source
        for source in HoldingSource
        if source.feature in shown and (source.permission is None or source.permission in user.permissions)
    )


def requires(permission: Permission) -> Callable[[User], None]:
    """A route that needs a permission beyond signing in: 403 without it. 403 never signs anyone out."""

    def check(user: CurrentUser) -> None:
        if permission not in user.permissions:
            raise AdministratorsOnly("Administrators only.")

    return check


async def backtest_turn(request: Request, runtime: RuntimeDependency, user: CurrentUser) -> AsyncGenerator[None]:
    """
    A strategy backtest or a ranking backtest holds one of the server's replays from its turn to its answer: it waits
    while the server replays accounts.max_concurrent_backtests, administrators' included. 429 (TooManyBacktests) while
    accounts.max_backtests_per_user of the user's own replay or wait. The app's lifespan created the replays.
    """
    replays: BacktestReplays = request.app.state.backtest_replays
    max_replaying, max_per_user = runtime.config.accounts.max_concurrent_backtests, runtime.config.accounts.max_backtests_per_user

    async with replays.turn(user.user_id, max_replaying, max_per_user):
        yield


def user_pipeline(runtime: RuntimeDependency, user: CurrentUser) -> Pipeline:
    """The signed-in user's own Pipeline, on their mock account: every private route but a run's or an account's broker choice."""
    return runtime.pipeline_for(user, ExecutionProvider.MOCK)


def broker_pipeline(runtime: RuntimeDependency, user: CurrentUser, broker: ExecutionProvider = ExecutionProvider.MOCK) -> Pipeline:
    """
    The signed-in user's own Pipeline on the broker the request's `broker` query names, the mock account by default:
    Buzz, Intraday and a manual BUY order on it, and the account page reads it. 403 real_broker_refused for a real
    broker without USE_REAL_BROKER, 403 broker_unavailable while its login is down or the site offers none, before any
    run starts; the order gates check both again at each order.
    """
    return runtime.pipeline_for(user, broker)


def signed_out_pipeline(runtime: RuntimeDependency) -> Pipeline:
    """The public routes and the LINE webhook. Its ports that hold users' data refuse, so it reads nobody's data."""
    return runtime.signed_out


UserPipeline = Annotated[Pipeline, Depends(user_pipeline)]
BrokerPipeline = Annotated[Pipeline, Depends(broker_pipeline)]
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
        path=API_PATH,
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path=API_PATH, secure=request.url.scheme == "https", httponly=True, samesite="strict")


def set_flow_cookie(request: Request, response: Response, flow: SignInFlow) -> None:
    """
    The flow a sign-in with Google started, for the browser to bring back from Google: HttpOnly, Path=/v1/auth/google,
    for the flow's lifetime as a Max-Age, Secure when the request came over https. SameSite=Lax, not Strict: Google's
    redirect back is a navigation from another site, which carries a Lax cookie and never a Strict one.
    """
    response.set_cookie(
        FLOW_COOKIE,
        urlsafe_b64encode(FLOW_JSON.dump_json(flow)).decode(),
        max_age=int((flow.expires_at - flow.started_at).total_seconds()),
        path=FLOW_PATH,
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="lax",
    )


def flow_of(request: Request) -> SignInFlow | None:
    """The flow the browser's cookie carries; None without the cookie or with one this app did not write."""
    try:
        return FLOW_JSON.validate_json(urlsafe_b64decode(request.cookies.get(FLOW_COOKIE, "")))
    except ValueError:
        return None


def back_to_app(request: Request, path: str, outcome: str | None = None) -> RedirectResponse:
    """
    Sends the browser from a Google endpoint to a page of the web app, with what happened as ?google=, and ends the
    flow: its cookie is cleared, so a return from Google works once.
    """
    response = RedirectResponse(f"{path}?google={outcome}" if outcome else path, status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(FLOW_COOKIE, path=FLOW_PATH, secure=request.url.scheme == "https", httponly=True, samesite="lax")
    return response


def client_of(request: Request) -> str:
    """
    The address the attempt limits count by. Behind a reverse proxy it is the visitor's only when uvicorn trusts the
    proxy's address (FORWARDED_ALLOW_IPS), as compose.yml sets it; otherwise every visitor counts as the proxy.
    """
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
RealtimeQuotes = Depends(require_realtime_quotes)
QuoteLogin = Depends(require_quote_login)
Mops = Depends(require_mops)
AccountShown = Depends(require_account_shown)
OrderingShown = Depends(require_ordering_shown)
HoldingSources = Annotated[frozenset[HoldingSource], Depends(holding_sources)]
RealBrokerHolder = Depends(requires(Permission.USE_REAL_BROKER))
"""The SinoPac account's own routes: 403 for a user who may not hold the real broker, whatever the site shows."""
ShowsRuns = shows(*(feature for feature in Feature if feature.run_start))
"""A run's own pages: its state, its decisions and its orders, for a viewer who may start at least one kind of run."""
PrivateAccess = Depends(current_user)
"""Every private route: a signed-in user. Whose data it reaches is the Pipeline's, built for that user."""
BacktestTurn = Depends(backtest_turn)
ManageUsers = Depends(requires(Permission.MANAGE_USERS))
EditSystemSettings = Depends(requires(Permission.EDIT_SYSTEM_SETTINGS))
