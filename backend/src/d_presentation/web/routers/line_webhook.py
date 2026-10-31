from typing import Annotated

from fastapi import APIRouter, Header, Request

from d_presentation.dependencies import create_line_webhook_handler
from d_presentation.web.dependencies import RuntimeDependency

router = APIRouter()


@router.post("")
async def handle_line_webhook(request: Request, runtime: RuntimeDependency, x_line_signature: Annotated[str | None, Header()] = None):
    await create_line_webhook_handler(runtime).handle(request, x_line_signature)
    return {"status": "ok"}
