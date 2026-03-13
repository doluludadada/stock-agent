from functools import lru_cache

from b_application.schemas.config import AppConfig
from c_infrastructure.system.config_loader import load_settings


@lru_cache
def get_settings() -> AppConfig:
    return load_settings()


# @lru_cache
# def get_logger() -> ILoggingProvider:
#     settings = get_settings()
#     return LoggerService(level=settings.behavior.log_level)


# # @lru_cache
# # def get_repository() -> IConversationRepository:
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
#     repo: IConversationRepository = Depends(get_repository),
#     config: AppConfig = Depends(get_settings),
#     logger: ILoggingProvider = Depends(get_logger),
# ) -> ContextLoader:
#     return ContextLoader(repository=repo, config=config, logger=logger)


# def get_state_manager(
#     repo: IConversationRepository = Depends(get_repository),
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
#     return LineSecurityService(channel_secret=settings.line.channel_secret, logger=logger)


# ---------------------------------------------------------------------------- #
#                         Analysis Pipeline Factories                          #
# ---------------------------------------------------------------------------- #
