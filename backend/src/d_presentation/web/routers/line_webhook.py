from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from c_infrastructure.platforms.line.line_handler import LineWebhookHandler
from d_presentation.dependencies.chat import get_line_handler

router = APIRouter()


@router.post("")
async def handle_line_webhook(
    request: Request,
    handler: Annotated[LineWebhookHandler, Depends(get_line_handler)],
    x_line_signature: Annotated[str | None, Header()] = None,
):
    await handler.handle(request, x_line_signature)
    return {"status": "ok"}
