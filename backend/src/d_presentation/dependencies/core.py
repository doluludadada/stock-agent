# src/d_presentation/dependencies/core.py

from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.notification_provider import INotificationProvider
from b_application.schemas.config import AppConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.platforms.line.line_notification_adapter import LineNotificationAdapter
from c_infrastructure.system.config_loader import load_settings
from c_infrastructure.system.logger_service import LoggerService
from c_infrastructure.system.market_clock import TaiwanMarketClock


@lru_cache
def get_settings() -> AppConfig:
    return load_settings()


def get_logger(
    config: Annotated[AppConfig, Depends(get_settings)],
) -> ILoggingProvider:
    return LoggerService(level=config.behavior.log_level)


@lru_cache
def get_market_clock() -> IMarketClock:
    return TaiwanMarketClock()


def get_db_connector(
    config: Annotated[AppConfig, Depends(get_settings)],
    logger: Annotated[ILoggingProvider, Depends(get_logger)],
) -> DatabaseConnector:
    return DatabaseConnector(
        config=config,
        logger=logger,
    )


async def get_db_session(
    connector: Annotated[DatabaseConnector, Depends(get_db_connector)],
) -> AsyncGenerator[AsyncSession]:
    async with connector.get_session() as session:
        yield session


def get_notification_provider(
    config: Annotated[AppConfig, Depends(get_settings)],
    logger: Annotated[ILoggingProvider, Depends(get_logger)],
) -> INotificationProvider | None:
    if not config.notifications.enabled:
        return None

    return LineNotificationAdapter(config=config, logger=logger)
