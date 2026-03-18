import os
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from d_presentation.web.routers.api_v1 import router as api_v1_router

src_path = str(Path(__file__).parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)


app = FastAPI(
    title="TW-Stock-Alpha-Agent",
    description="Automated stock analysis and trading pipeline API.",
    version="0.1.0",
)

app.include_router(api_v1_router)


def main():
    """
    Main entry point for the application.
    Starts the Uvicorn server.
    """
    port = int(os.environ.get("PORT", 8800))

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,  # Set to False in production
        log_level="info",
    )


if __name__ == "__main__":
    main()
