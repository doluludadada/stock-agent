import base64
import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import ValidationError

from c_infrastructure.platforms.line.dto.line_dto import LineEventType, LineMessageType, LineWebhookPayload
from d_presentation.dependencies import RuntimeDependency

router = APIRouter()


@router.post("")
async def handle_line_webhook(request: Request, runtime: RuntimeDependency, x_line_signature: Annotated[str | None, Header()] = None):
    """Answers each text message in a LINE webhook call. A call without LINE's signature over its body is refused."""
    body = await request.body()
    channel_secret = runtime.config.line.channel_secret

    if not channel_secret:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "LINE_CHANNEL_SECRET is not set, so LINE calls cannot be verified.")

    expected_signature = base64.b64encode(hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()).decode("utf-8")

    if x_line_signature is None or not hmac.compare_digest(x_line_signature, expected_signature):
        runtime.logger.warning("LINE webhook refused: the X-Line-Signature header is missing or does not match the body.")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")

    try:
        payload = LineWebhookPayload.model_validate_json(body)
    except ValidationError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid payload: {error}") from error

    for event in payload.events:
        message = event.message

        if event.type == LineEventType.MESSAGE and message and message.type == LineMessageType.TEXT and message.text:
            await runtime.pipeline.reply_to_chat(user_id=event.source.userId, content=message.text)

    return {"status": "ok"}
