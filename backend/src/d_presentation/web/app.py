from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from d_presentation.dependencies import Runtime
from d_presentation.web.routers.api_v1 import router as api_v1_router
from d_presentation.web.workflow_runs import WorkflowRuns

SETTINGS_PAGE = Path(__file__).with_name("settings.html")

DESCRIPTION = """
Runs the stock-agent workflows and reads what they recorded, on the same runtime as the CLI.

No endpoint places, cancels or modifies an order. The API starts only Full Cycle and specific-stock analysis,
which never reach order execution, and it offers no manual BUY. Orders come from the CLI's Buzz, Intraday and
confirmed manual BUY only.

Workflows run in the background, one at a time: a start answers 202 with the run id, and GET /v1/runs/{run_id}
reports the run's state and its record.

Every write needs `Authorization: Bearer <API_TOKEN>` and `"confirm": true` in its body. While API_TOKEN is unset,
writes answer 403. Reads need no token.

The technical settings page is at /ui/settings.
"""


def create_app(open_runtime: Callable[[], AbstractAsyncContextManager[Runtime]]) -> FastAPI:
    """
    The FastAPI app. Its lifespan opens the runtime once, through the same trading-setup checks as the CLI, and at
    shutdown cancels a still-running workflow before the database closes, so its record ends as aborted.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with open_runtime() as runtime:
            app.state.runtime = runtime
            app.state.workflow_runs = workflow_runs = WorkflowRuns(runtime.logger)

            try:
                yield

            finally:
                await workflow_runs.stop()

    app = FastAPI(title="TW-Stock-Alpha-Agent", description=DESCRIPTION, version="0.1.0", lifespan=lifespan)
    app.include_router(api_v1_router)

    @app.get("/ui/settings", include_in_schema=False)
    async def settings_page() -> FileResponse:
        """The technical settings page: it edits the indicator parameters through PUT /v1/technical-settings, which validates them."""
        return FileResponse(SETTINGS_PAGE, media_type="text/html")

    return app
