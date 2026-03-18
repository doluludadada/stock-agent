from functools import lru_cache

from fastapi import Depends

from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.chat.web_search_provider import IWebSearchProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.signal_repository import ISignalRepository
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from b_application.schemas.config import AppConfig
from c_infrastructure.ai_models.factory import AiAdapterFactory
from c_infrastructure.database.chroma.chroma_repository import ChromaRepositoryAdapter
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.signal_repository import SignalRepository
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from d_presentation.dependencies.core import get_db_connector, get_logger, get_settings
from d_presentation.dependencies.providers import get_tavily_search


@lru_cache
def get_ai_provider(
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
    web_search: IWebSearchProvider = Depends(get_tavily_search),
) -> IAiProvider:
    factory = AiAdapterFactory(config=config, logger=logger, web_search=web_search)
    return factory.create_adapter()


@lru_cache
def get_chroma_repository(
    config: AppConfig = Depends(get_settings), logger: ILoggingProvider = Depends(get_logger)
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


def get_signal_repository(
    connector: DatabaseConnector = Depends(get_db_connector), logger: ILoggingProvider = Depends(get_logger)
) -> ISignalRepository:
    return SignalRepository(db=connector, logger=logger)


def get_watchlist_repository(
    connector: DatabaseConnector = Depends(get_db_connector), logger: ILoggingProvider = Depends(get_logger)
) -> IWatchlistRepository:
    return WatchlistRepository(db=connector, logger=logger)


def get_execution_provider() -> IExecutionProvider:
    # Requires a real broker execution adapter (e.g. Shioaji) Implementation here.
    # Currently raising NotImplemented as it assumes DEV environment mocking in use calls or another injection.
    raise NotImplementedError("ExecutionProvider not fully mapped to an adapter.")
