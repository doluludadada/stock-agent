from functools import lru_cache

from fastapi import Depends

from src.a_domain.ports.analysis.quality_filter_provider import IQualityFilterProvider
from src.a_domain.ports.chat.chat_styler_provider import IChatStylerProvider
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.a_domain.ports.system.platform_provider import IPlatformProvider
from src.a_domain.ports.system.repository_provider import IRepositoryProvider
from src.a_domain.rules.collect.content import ContentRelevanceRule
from src.a_domain.rules.process.indicators.ma_rule import PriceAboveMovingAverageRule
from src.a_domain.rules.process.indicators.macd_rule import BullishMacdCrossoverRule
from src.a_domain.rules.process.indicators.rsi_rule import RsiHealthyRule
from src.a_domain.rules.process.policies.technical_screening import TechnicalScreeningPolicy
from src.a_domain.types.constants import FINANCIAL_KEYWORDS_TW
from src.a_domain.types.enums import DatabaseProvider
from src.b_application.schemas.config import AppConfig
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
def get_logger() -> ILoggingProvider:
    settings = get_settings()
    return LoggerService(level=settings.log_level)


@lru_cache
def get_repository() -> IRepositoryProvider:
    settings = get_settings()
    logger = get_logger()

    if settings.database_provider == DatabaseProvider.CHROMA:
        return ChromaRepositoryAdapter(config=settings, logger=logger)
    if settings.database_provider == DatabaseProvider.MEMORY:
        return InMemoryRepositoryAdapter(logger=logger)

    logger.warning(f"Unknown database provider '{settings.database_provider}'. Falling back to InMemory.")
    return InMemoryRepositoryAdapter(logger=logger)


@lru_cache
def get_styler() -> IChatStylerProvider:
    return ChatStylerService()


@lru_cache
def get_platform_adapter() -> IPlatformProvider:
    settings = get_settings()
    logger = get_logger()
    return LinePlatformAdapter(config=settings, logger=logger)


# --- Pipeline Assembly ---


def get_context_loader(
    repo: IRepositoryProvider = Depends(get_repository),
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> ContextLoader:
    return ContextLoader(repository=repo, config=config, logger=logger)


def get_state_manager(
    repo: IRepositoryProvider = Depends(get_repository),
    logger: ILoggingProvider = Depends(get_logger),
) -> StateManager:
    return StateManager(repository=repo, logger=logger)


def get_dispatcher(
    platform: IPlatformProvider = Depends(get_platform_adapter),
    logger: ILoggingProvider = Depends(get_logger),
) -> Dispatcher:
    return Dispatcher(platform=platform, logger=logger)


# --- Webhook Handler ---


def get_line_security(
    settings: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> LineSecurityService:
    return LineSecurityService(channel_secret=settings.line_channel_secret, logger=logger)


# ---------------------------------------------------------------------------- #
#                         Analysis Pipeline Factories                          #
# ---------------------------------------------------------------------------- #


def get_quality_filter(
    config: AppConfig = Depends(get_settings),
) -> IQualityFilterProvider:
    """Factory for IQualityFilterProvider using ContentRelevanceRule."""
    return ContentRelevanceRule(
        spam_keywords=config.collect_spam_keywords,
        financial_keywords=FINANCIAL_KEYWORDS_TW,
    )


def get_screening_policy() -> TechnicalScreeningPolicy:
    """Factory for TechnicalScreeningPolicy with standard rules."""
    standard_rules = [
        PriceAboveMovingAverageRule(),
        BullishMacdCrossoverRule(),
        RsiHealthyRule(),
    ]
    momentum_safety_rules = [
        RsiHealthyRule(),
    ]
    return TechnicalScreeningPolicy(
        standard_rules=standard_rules,
        momentum_safety_rules=momentum_safety_rules,
    )
