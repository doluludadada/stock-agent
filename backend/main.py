import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn

from b_application.config.settings_loader import InvalidSettingsError
from c_infrastructure.database.db_connector import OutdatedDatabaseError
from d_presentation.dependencies import Runtime, TradingSetupError, open_runtime
from d_presentation.web.app import create_app


@asynccontextmanager
async def open_runtime_or_exit() -> AsyncGenerator[Runtime]:
    """
    The runtime, or, as in the CLI, invalid settings, an outdated database or a refused trading setup printed alone with
    exit status 1.
    uvicorn prints a traceback around any exception that leaves the app's lifespan, and SystemExit is one too.
    """
    try:
        async with open_runtime() as runtime:
            yield runtime
    except (InvalidSettingsError, OutdatedDatabaseError, TradingSetupError) as error:
        print(error, file=sys.stderr, flush=True)
        os._exit(1)


app = create_app(open_runtime_or_exit)


def main() -> None:
    """
    Starts the Web API on one worker process: background runs, their one-at-a-time lock and the settings revision the
    server started with live in that process. HOST defaults to the loopback address; serve another network only
    behind a TLS reverse proxy that adds the host name to api.allowed_hosts.
    """
    uvicorn.run(
        "main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 8800)),
        workers=1,
        reload=os.environ.get("RELOAD") == "1",
        log_level="info",
    )


if __name__ == "__main__":
    main()
