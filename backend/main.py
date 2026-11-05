import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn

from d_presentation.dependencies import STARTUP_REFUSALS
from d_presentation.live_runtime import RuntimeSwitch, open_runtime_switch
from d_presentation.web.app import create_app


@asynccontextmanager
async def open_runtime_switch_or_exit() -> AsyncGenerator[RuntimeSwitch]:
    """
    The process's runtimes, or, as in the CLI, invalid settings, an outdated database, a refused trading setup or a
    malformed or wrong accounts key printed alone with exit status 1.
    uvicorn prints a traceback around any exception that leaves the app's lifespan, and SystemExit is one too.
    """
    try:
        async with open_runtime_switch() as switch:
            yield switch
    except STARTUP_REFUSALS as error:
        print(error, file=sys.stderr, flush=True)
        os._exit(1)


app = create_app(open_runtime_switch_or_exit)


def main() -> None:
    """
    Starts the Web API on one worker process: background runs, their one-at-a-time lock and the runtimes the settings
    files were loaded into live in that process. HOST defaults to the loopback address; serve another network only
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
