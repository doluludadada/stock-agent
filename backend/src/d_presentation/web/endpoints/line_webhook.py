# src/d_presentation/web/endpoints/line_webhook.py

from fastapi import APIRouter, Depends, Header, Request

from c_infrastructure.platforms.line.line_handler import LineWebhookHandler

router = APIRouter()

@router.post('')
async def handle_line_webhook(
    request: Request, 
    x_line_signature: str | None = Header(None), 
    handler: LineWebhookHandler = Depends(get_line_handler)
):
    await handler.handle(request, x_line_signature)
    return {'status': 'ok'}


