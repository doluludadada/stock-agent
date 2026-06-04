from fastapi import Depends

from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.config import AppConfig
from b_application.use_cases.chat.ai_processor import AiProcessor
from b_application.use_cases.chat.chat_pipeline import ChatPipeline
from b_application.use_cases.chat.context_loader import ContextLoader
from b_application.use_cases.chat.dispatcher import Dispatcher
from b_application.use_cases.chat.state_manager import StateManager
from c_infrastructure.platforms.line.line_adapter import LinePlatformAdapter
from c_infrastructure.platforms.line.line_handler import LineWebhookHandler
from c_infrastructure.platforms.line.line_security import LineSecurityService
from c_infrastructure.system.chat_styler_service import ChatStylerService
from d_presentation.dependencies.core import get_logger, get_settings
from d_presentation.dependencies.repositories import get_ai_provider, get_conversation_repository


def get_chat_styler() -> ChatStylerService:
    return ChatStylerService()


def get_line_platform(
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> LinePlatformAdapter:
    return LinePlatformAdapter(config=config, logger=logger)


def get_line_security(
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> LineSecurityService:
    return LineSecurityService(channel_secret=config.line.channel_secret, logger=logger)


def get_context_loader(
    repository: IConversationRepository = Depends(get_conversation_repository),
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> ContextLoader:
    return ContextLoader(repository=repository, config=config, logger=logger)


def get_ai_processor(
    ai_provider: IAiProvider = Depends(get_ai_provider),
    chat_styler_provider: ChatStylerService = Depends(get_chat_styler),
    logger: ILoggingProvider = Depends(get_logger),
) -> AiProcessor:
    return AiProcessor(
        ai_provider=ai_provider,
        chat_styler_provider=chat_styler_provider,
        logger=logger,
    )


def get_state_manager(
    repository: IConversationRepository = Depends(get_conversation_repository),
    logger: ILoggingProvider = Depends(get_logger),
) -> StateManager:
    return StateManager(repository=repository, logger=logger)


def get_dispatcher(
    platform_provider: LinePlatformAdapter = Depends(get_line_platform),
    logger: ILoggingProvider = Depends(get_logger),
) -> Dispatcher:
    return Dispatcher(platform_provider=platform_provider, logger=logger)


def get_chat_pipeline(
    loader: ContextLoader = Depends(get_context_loader),
    processor: AiProcessor = Depends(get_ai_processor),
    manager: StateManager = Depends(get_state_manager),
    dispatcher: Dispatcher = Depends(get_dispatcher),
    config: AppConfig = Depends(get_settings),
) -> ChatPipeline:
    return ChatPipeline(
        loader=loader,
        processor=processor,
        manager=manager,
        dispatcher=dispatcher,
        config=config,
    )


def get_line_handler(
    security: LineSecurityService = Depends(get_line_security),
    pipeline: ChatPipeline = Depends(get_chat_pipeline),
) -> LineWebhookHandler:
    return LineWebhookHandler(security_service=security, pipeline=pipeline)
