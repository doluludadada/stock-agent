from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from b_application.use_cases.chat.ai_processor import AiProcessor
from b_application.use_cases.chat.chat_pipeline import ChatPipeline
from b_application.use_cases.chat.context_loader import ContextLoader
from b_application.use_cases.chat.dispatcher import Dispatcher
from b_application.use_cases.chat.state_manager import StateManager
from c_infrastructure.platforms.line.line_adapter import LinePlatformAdapter
from c_infrastructure.platforms.line.line_handler import LineWebhookHandler
from c_infrastructure.platforms.line.line_security import LineSecurityService
from c_infrastructure.system.chat_styler_service import ChatStylerService
from d_presentation.web.dependencies import RuntimeDependency

router = APIRouter()


def get_line_handler(runtime: RuntimeDependency) -> LineWebhookHandler:
    """Built per request: the LINE adapters refuse to build without LINE credentials, and only this route needs them."""
    config, logger = runtime.config, runtime.logger

    pipeline = ChatPipeline(
        loader=ContextLoader(repository=runtime.conversation_repository, config=config, logger=logger),
        processor=AiProcessor(ai_provider=runtime.ai_provider, chat_styler_provider=ChatStylerService(), logger=logger),
        manager=StateManager(repository=runtime.conversation_repository, logger=logger),
        dispatcher=Dispatcher(platform_provider=LinePlatformAdapter(config=config, logger=logger), logger=logger),
        config=config,
    )

    return LineWebhookHandler(
        security_service=LineSecurityService(channel_secret=config.line.channel_secret, logger=logger), pipeline=pipeline
    )


@router.post("")
async def handle_line_webhook(
    request: Request,
    handler: Annotated[LineWebhookHandler, Depends(get_line_handler)],
    x_line_signature: Annotated[str | None, Header()] = None,
):
    await handler.handle(request, x_line_signature)
    return {"status": "ok"}
