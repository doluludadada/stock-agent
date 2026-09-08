# backend/src/d_presentation/dependencies/repositories.py

from typing import Annotated

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
from a_domain.types.enums import ExecutionProvider
from b_application.schemas.config import AppConfig
from c_infrastructure.ai_models.factory import AiAdapterFactory
from c_infrastructure.database.chroma.chroma_repository import ChromaRepositoryAdapter
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.signal_repository import SignalRepository
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from c_infrastructure.trading.mock.mock_execution_provider import MockExecutionProvider
from d_presentation.dependencies.core import get_db_connector, get_logger, get_market_clock, get_settings
from d_presentation.dependencies.providers import get_tavily_search


def get_ai_provider(
    config: Annotated[AppConfig, Depends(get_settings)],
    logger: Annotated[ILoggingProvider, Depends(get_logger)],
    web_search_provider: Annotated[IWebSearchProvider | None, Depends(get_tavily_search)],
) -> IAiProvider:
    factory = AiAdapterFactory(config=config, logger=logger, web_search_provider=web_search_provider)
    return factory.create_adapter()


def get_chroma_repository(
    config: Annotated[AppConfig, Depends(get_settings)],
    logger: Annotated[ILoggingProvider, Depends(get_logger)],
) -> ChromaRepositoryAdapter:
    return ChromaRepositoryAdapter(config=config, logger=logger)


def get_conversation_repository(
    repo: Annotated[ChromaRepositoryAdapter, Depends(get_chroma_repository)],
) -> IConversationRepository:
    return repo


def get_knowledge_repository(
    repo: Annotated[ChromaRepositoryAdapter, Depends(get_chroma_repository)],
) -> IKnowledgeRepository:
    return repo


def get_signal_repository(
    db: Annotated[DatabaseConnector, Depends(get_db_connector)],
    logger: Annotated[ILoggingProvider, Depends(get_logger)],
) -> ISignalRepository:
    return SignalRepository(db=db, logger=logger)


def get_watchlist_repository(
    db: Annotated[DatabaseConnector, Depends(get_db_connector)],
    logger: Annotated[ILoggingProvider, Depends(get_logger)],
    market_clock: Annotated[IMarketClock, Depends(get_market_clock)],
) -> IWatchlistRepository:
    return WatchlistRepository(
        db=db,
        logger=logger,
        market_clock=market_clock,
    )


def get_execution_provider(
    db: Annotated[DatabaseConnector, Depends(get_db_connector)],
    config: Annotated[AppConfig, Depends(get_settings)],
    logger: Annotated[ILoggingProvider, Depends(get_logger)],
) -> IExecutionProvider:
    if config.trading.execution_provider != ExecutionProvider.MOCK:
        raise NotImplementedError(f"Execution provider is not wired yet: {config.trading.execution_provider.value}")

    return MockExecutionProvider(
        db=db,
        config=config,
        logger=logger,
    )
