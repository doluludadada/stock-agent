from functools import lru_cache
from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.notification_provider import INotificationProvider
from b_application.schemas.config import AppConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.platforms.line.line_notification_adapter import LineNotificationAdapter
from c_infrastructure.system.config_loader import load_settings
from c_infrastructure.system.logger_service import LoggerService


@lru_cache
def get_settings() -> AppConfig:
    return load_settings()


@lru_cache
def get_logger(config: AppConfig = Depends(get_settings)) -> ILoggingProvider:
    return LoggerService(level=config.behavior.log_level)


@lru_cache
def get_db_connector(config: AppConfig = Depends(get_settings), logger: ILoggingProvider = Depends(get_logger)) -> DatabaseConnector:
    return DatabaseConnector(config=config, logger=logger)


async def get_db_session(
    connector: DatabaseConnector = Depends(get_db_connector),
) -> AsyncGenerator[AsyncSession, None]:
    async with connector.get_session() as session:
        yield session


@lru_cache
def get_notification_provider(
    config: AppConfig = Depends(get_settings), logger: ILoggingProvider = Depends(get_logger)
) -> INotificationProvider:
    return LineNotificationAdapter(config=config, logger=logger)
