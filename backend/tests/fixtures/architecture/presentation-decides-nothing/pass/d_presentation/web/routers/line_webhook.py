from fastapi import APIRouter, Request

from a_domain.types.enums import MessageRole
from d_presentation.dependencies import RuntimeDependency

router = APIRouter()


@router.post("/line/webhook")
async def receive(request: Request, runtime: RuntimeDependency) -> str:
    channel_secret = runtime.config.line.channel_secret
    await runtime.pipeline.reply_to_chat(await request.body(), channel_secret)
    return MessageRole.ASSISTANT
