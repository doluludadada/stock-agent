from functools import lru_cache

from fastapi import Depends

from src.a_domain.ports.analysis.quality_filter_port import IQualityFilterPort
from src.a_domain.ports.chat.chat_styler_port import IChatStylerPort
from src.a_domain.ports.system.logging_port import ILoggingPort
from src.a_domain.ports.system.platform_port import IPlatformPort
from src.a_domain.ports.system.repository_port import IRepositoryPort
from src.a_domain.rules.collect.quality_filter import ArticleQualityFilter
from src.a_domain.rules.process.ma_rule import PriceAboveMovingAverageRule
from src.a_domain.rules.process.macd_rule import BullishMacdCrossoverRule
from src.a_domain.rules.process.rsi_rule import RsiHealthyRule
from src.a_domain.rules.process.technical_screening import TechnicalScreeningPolicy
from src.a_domain.types.enums import DatabaseProvider
from src.b_application.configuration.schemas import AppConfig
from src.b_application.use_cases.chat.context_loader import ContextLoader
from src.b_application.use_cases.chat.dispatcher import Dispatcher
from src.b_application.use_cases.chat.state_manager import StateManager
from src.c_infrastructure.config.loader import load_settings
from src.c_infrastructure.persistence.chroma.chroma_repository import (
    ChromaRepositoryAdapter,
)
from src.c_infrastructure.persistence.inmemory_repository import (
    InMemoryRepositoryAdapter,
)
from src.c_infrastructure.platforms.line.line_adapter import LinePlatformAdapter
from src.c_infrastructure.platforms.line.line_security import LineSecurityService
from src.c_infrastructure.services.chat_styler_service import ChatStylerService
from src.c_infrastructure.services.logger_service import LoggerService


@lru_cache
def get_settings() -> AppConfig:
    return load_settings()


@lru_cache
def get_logger() -> ILoggingPort:
    settings = get_settings()
    return LoggerService(level=settings.log_level)


@lru_cache
def get_repository() -> IRepositoryPort:
    # Call dependencies directly inside to keep signature clean for lru_cache
    settings = get_settings()
    logger = get_logger()

    if settings.database_provider == DatabaseProvider.CHROMA:
        return ChromaRepositoryAdapter(config=settings, logger=logger)
    if settings.database_provider == DatabaseProvider.MEMORY:
        return InMemoryRepositoryAdapter(logger=logger)

    logger.warning(f"Unknown database provider '{settings.database_provider}'. Falling back to InMemory.")
    return InMemoryRepositoryAdapter(logger=logger)


@lru_cache
def get_styler() -> IChatStylerPort:
    return ChatStylerService()


@lru_cache
def get_platform_adapter() -> IPlatformPort:
    settings = get_settings()
    logger = get_logger()
    return LinePlatformAdapter(config=settings, logger=logger)


# --- Pipeline Assembly ---


def get_context_loader(
    repo: IRepositoryPort = Depends(get_repository),
    config: AppConfig = Depends(get_settings),
    logger: ILoggingPort = Depends(get_logger),
) -> ContextLoader:
    return ContextLoader(repository=repo, config=config, logger=logger)


def get_state_manager(
    repo: IRepositoryPort = Depends(get_repository),
    logger: ILoggingPort = Depends(get_logger),
) -> StateManager:
    return StateManager(repository=repo, logger=logger)


def get_dispatcher(
    platform: IPlatformPort = Depends(get_platform_adapter),
    logger: ILoggingPort = Depends(get_logger),
) -> Dispatcher:
    return Dispatcher(platform=platform, logger=logger)


# --- Webhook Handler ---


def get_line_security(
    settings: AppConfig = Depends(get_settings),
    logger: ILoggingPort = Depends(get_logger),
) -> LineSecurityService:
    return LineSecurityService(channel_secret=settings.line_channel_secret, logger=logger)


# ---------------------------------------------------------------------------- #
#                         Analysis Pipeline Factories                          #
# ---------------------------------------------------------------------------- #


@lru_cache
def get_quality_filter() -> IQualityFilterPort:
    """Factory for IQualityFilterPort using ArticleQualityFilter."""
    return ArticleQualityFilter()


@lru_cache
def get_screening_policy() -> TechnicalScreeningPolicy:
    """Factory for TechnicalScreeningPolicy with standard rules."""
    rules = [
        PriceAboveMovingAverageRule(),
        BullishMacdCrossoverRule(),
        RsiHealthyRule(),
    ]
    return TechnicalScreeningPolicy(rules)


# --- Analysis Use Case Factories ---


# --- Analysis Pipeline Assembly ---
