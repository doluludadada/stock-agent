import chromadb

from a_domain.model.chat.conversation import Conversation
from a_domain.model.market.stock import Stock
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.config import AppConfig
from c_infrastructure.database.chroma.mapper import ConversationMapper
from c_infrastructure.database.chroma.schema import ChromaCollection, ChromaResultKey


class ChromaRepositoryAdapter(IConversationRepository, IKnowledgeRepository):
    def __init__(self, config: AppConfig, logger: ILoggingProvider) -> None:
        self._logger = logger
        self._logger.info(f"Initializing ChromaDB at: {config.db.chroma_persist_path}")

        self._client = chromadb.PersistentClient(path=config.db.chroma_persist_path)

        self._collection = self._client.get_or_create_collection(name=ChromaCollection.CHAT_HISTORY)

    async def get_conversation_by_user_id(self, user_id: str) -> Conversation | None:
        self._logger.debug(f"Fetching conversation for user_id: {user_id}")

        try:
            result = self._collection.get(ids=[user_id])
            documents = result.get(ChromaResultKey.DOCUMENTS)

            if not documents:
                return None
            return ConversationMapper.to_domain(documents[0])

        except Exception as e:
            self._logger.error(f"Error fetching conversation for user {user_id}: {e}")
            return None

    async def save(self, conversation: Conversation) -> bool:
        self._logger.debug(f"Saving conversation for user_id: {conversation.user_id}")

        try:
            json_str, metadata = ConversationMapper.to_persistence(conversation)

            self._collection.upsert(
                ids=[conversation.user_id],
                documents=[json_str],
                metadatas=[metadata],
            )
            return True

        except Exception as e:
            self._logger.critical(f"Error saving conversation to Chroma: {e}")
            return False

    async def search(self, query: str, limit: int = 3) -> str:
        """Retrieves context for Chatbot or Pipeline."""
        self._logger.debug(f"Stub: RAG Search for '{query}' (limit: {limit})")
        return ""

    async def save_analysis(self, context: Stock) -> None:
        """Saves analysis result into the knowledge base (RAG memory)."""
        self._logger.debug(f"Stub: RAG Save Analysis for stock '{context.stock_id}'")
        pass
