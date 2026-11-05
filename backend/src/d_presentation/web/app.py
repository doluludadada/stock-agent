from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from a_domain.types.errors import ListingUnavailableError, TechnicalSettingsConflictError
from d_presentation.dependencies import Runtime, create_market_valuation_cache, create_workflow_runs
from d_presentation.web.routers.api_v1 import router as api_v1_router

DESCRIPTION = """
Runs the stock-agent workflows and reads what they recorded, on the same runtime as the CLI.

Scopes. Public: the built-in strategies and market data (`/v1/market`). Owner,
`Authorization: Bearer <API_TOKEN>`: every write and every read of private data (runs, decisions, orders,
watchlist, account, saved technical settings). Administrator, `Authorization: Bearer <ADMIN_API_TOKEN>`: only the
settings files under `/v1/admin`. A scope whose token is unset answers 403; the administrator scope also when
ADMIN_API_TOKEN equals API_TOKEN. Every write repeats `"confirm": true` in its body.

Orders. Full Cycle, specific-stock analysis, valuation and market data never order. Buzz and Intraday send orders
through the same gates and trading journal as the CLI, and the API starts them only while the execution provider is
the mock broker (403 otherwise). No endpoint places, cancels or modifies an order by itself, and the API offers no
manual BUY.

Workflows run in the background, one at a time per server: a start answers 202 with the run id, and
GET /v1/runs/{run_id} reports the run's state and its record. Run the server with one worker process.
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
            {"detail": f"A request body may hold at most {MAX_BODY_BYTES} bytes, with a Content-Length."}, status_code=413
        )

    response = await call_next(request)

    if request.url.path.startswith("/v1"):
        response.headers.update(API_SECURITY_HEADERS)

    return response


async def answer_listing_unavailable(request: Request, error: ListingUnavailableError) -> JSONResponse:
    """Every route that reads the exchange listing answers 503 when it could not be loaded."""
    return JSONResponse({"detail": str(error)}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


async def answer_settings_conflict(request: Request, error: TechnicalSettingsConflictError) -> JSONResponse:
    """A read or a save of the technical settings that another save overtook answers 409: read them again."""
    return JSONResponse({"detail": str(error)}, status_code=status.HTTP_409_CONFLICT)


def create_app(open_runtime: Callable[[], AbstractAsyncContextManager[Runtime]]) -> FastAPI:
    """
    The FastAPI app. Its lifespan opens the runtime once, through the same trading-setup checks as the CLI, and at
    shutdown cancels a still-running workflow before the database closes, so its record ends as aborted.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        async with open_runtime() as runtime:
            app.state.runtime = runtime
            app.state.workflow_runs = workflow_runs = create_workflow_runs(runtime)
            app.state.market_valuation_cache = create_market_valuation_cache(runtime)

            try:
                yield

            finally:
                await workflow_runs.stop()

    app = FastAPI(title="TW-Stock-Alpha-Agent", description=DESCRIPTION, version="0.2.0", lifespan=lifespan)
    app.include_router(api_v1_router)

    app.middleware("http")(add_security_headers)
    app.exception_handler(ListingUnavailableError)(answer_listing_unavailable)
    app.exception_handler(TechnicalSettingsConflictError)(answer_settings_conflict)

    return app
