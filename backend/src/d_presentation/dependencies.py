from functools import lru_cache

from a_domain.ports.chat.chat_styler_provider import IChatStylerProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.platform_provider import IPlatformProvider
from a_domain.ports.system.repository_provider import IRepositoryProvider
from b_application.schemas.config import AppConfig
from b_application.use_cases.chat.context_loader import ContextLoader
from b_application.use_cases.chat.dispatcher import Dispatcher
from b_application.use_cases.chat.state_manager import StateManager
from c_infrastructure.services.config_loader import load_settings
from c_infrastructure.persistence.chroma.chroma_repository import (
    ChromaRepositoryAdapter,
)
from c_infrastructure.persistence.inmemory_repository import (
    InMemoryRepositoryAdapter,
)
from c_infrastructure.platforms.line.line_adapter import LinePlatformAdapter
from c_infrastructure.platforms.line.line_security import LineSecurityService
from c_infrastructure.services.chat_styler_service import ChatStylerService
from c_infrastructure.services.logger_service import LoggerService
from fastapi import Depends


@lru_cache
def get_settings() -> AppConfig:
    return load_settings()


# @lru_cache
# def get_logger() -> ILoggingProvider:
#     settings = get_settings()
#     return LoggerService(level=settings.log_level)


# # @lru_cache
# # def get_repository() -> IRepositoryProvider:
# # settings = get_settings()
# # logger = get_logger()


# @lru_cache
# def get_styler() -> IChatStylerProvider:
#     return ChatStylerService()


# @lru_cache
# def get_platform_adapter() -> IPlatformProvider:
#     settings = get_settings()
#     logger = get_logger()
#     return LinePlatformAdapter(config=settings, logger=logger)


# # --- Pipeline Assembly ---


# def get_context_loader(
#     repo: IRepositoryProvider = Depends(get_repository),
#     config: AppConfig = Depends(get_settings),
#     logger: ILoggingProvider = Depends(get_logger),
# ) -> ContextLoader:
#     return ContextLoader(repository=repo, config=config, logger=logger)


# def get_state_manager(
#     repo: IRepositoryProvider = Depends(get_repository),
#     logger: ILoggingProvider = Depends(get_logger),
# ) -> StateManager:
#     return StateManager(repository=repo, logger=logger)


# def get_dispatcher(
#     platform: IPlatformProvider = Depends(get_platform_adapter),
#     logger: ILoggingProvider = Depends(get_logger),
# ) -> Dispatcher:
#     return Dispatcher(platform=platform, logger=logger)


# # --- Webhook Handler ---


# def get_line_security(
#     settings: AppConfig = Depends(get_settings),
#     logger: ILoggingProvider = Depends(get_logger),
# ) -> LineSecurityService:
#     return LineSecurityService(channel_secret=settings.line_channel_secret, logger=logger)


# ---------------------------------------------------------------------------- #
#                         Analysis Pipeline Factories                          #
# ---------------------------------------------------------------------------- #
