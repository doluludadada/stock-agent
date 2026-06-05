# backend/src/d_presentation/dependencies/repositories.py

from functools import lru_cache

from fastapi import Depends

from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.chat.web_search_provider import IWebSearchProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.signal_repository import ISignalRepository
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from b_application.schemas.config import AppConfig
from c_infrastructure.ai_models.factory import AiAdapterFactory
from c_infrastructure.database.chroma.chroma_repository import ChromaRepositoryAdapter
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.signal_repository import SignalRepository
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from c_infrastructure.trading.mock.mock_execution_provider import MockExecutionProvider
from d_presentation.dependencies.core import get_db_connector, get_logger, get_market_clock, get_settings
from d_presentation.dependencies.providers import get_tavily_search


@lru_cache
def get_ai_provider(
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
    web_search_provider: IWebSearchProvider | None = Depends(get_tavily_search),
) -> IAiProvider:
    factory = AiAdapterFactory(config=config, logger=logger, web_search_provider=web_search_provider)
    return factory.create_adapter()


@lru_cache
def get_chroma_repository(
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> ChromaRepositoryAdapter:
    return ChromaRepositoryAdapter(config=config, logger=logger)


def get_conversation_repository(
    repo: ChromaRepositoryAdapter = Depends(get_chroma_repository),
) -> IConversationRepository:
    return repo


def get_knowledge_repository(
    repo: ChromaRepositoryAdapter = Depends(get_chroma_repository),
) -> IKnowledgeRepository:
    return repo


@lru_cache
def get_signal_repository(
    db: DatabaseConnector = Depends(get_db_connector),
    logger: ILoggingProvider = Depends(get_logger),
) -> ISignalRepository:
    return SignalRepository(db=db, logger=logger)


@lru_cache
def get_watchlist_repository(
    db: DatabaseConnector = Depends(get_db_connector),
    logger: ILoggingProvider = Depends(get_logger),
    market_clock: IMarketClock = Depends(get_market_clock),
) -> IWatchlistRepository:
    return WatchlistRepository(
        db=db,
        logger=logger,
        market_clock=market_clock,
    )


@lru_cache
def get_execution_provider(
    db: DatabaseConnector = Depends(get_db_connector),
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> IExecutionProvider:
    # TODO: Future - switch to ShioajiExecutionProvider when environment is LIVE.

    return MockExecutionProvider(
        db=db,
        config=config,
        logger=logger,
    )
