from fastapi import HTTPException, Request, status
from pydantic import ValidationError

from b_application.pipeline import Pipeline
from c_infrastructure.platforms.line.dto.line_dto import LineWebhookPayload
from c_infrastructure.platforms.line.line_constants import EVENT_TYPE_MESSAGE, MESSAGE_TYPE_TEXT
from c_infrastructure.platforms.line.line_security import LineSecurityService


class LineWebhookHandler:
    def __init__(self, security_service: LineSecurityService, pipeline: Pipeline):
        self._security_service = security_service
        self._pipeline = pipeline

    async def handle(self, request: Request, signature: str | None):
        body = await request.body()
        if not self._security_service.verify_signature(body, signature):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")

        try:
            payload = LineWebhookPayload.model_validate_json(body)
        except ValidationError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid payload: {error}") from error

        for event in payload.events:
            if event.type == EVENT_TYPE_MESSAGE and event.message and (event.message.type == MESSAGE_TYPE_TEXT):
                user_id = event.source.userId
                text_content = event.message.text
                if text_content:
                    await self._pipeline.reply_to_chat(user_id=user_id, content=text_content)
