import chromadb

from backend.src.a_domain.model.chat.conversation import Conversation
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.a_domain.ports.system.repository_provider import IRepositoryProvider
from backend.src.b_application.schemas.config import AppConfig
from backend.src.c_infrastructure.persistence.chroma.mapper import ConversationMapper
from backend.src.c_infrastructure.persistence.chroma.schema import ChromaCollection, ChromaResultKey


class ChromaRepositoryAdapter(IRepositoryProvider):
    def __init__(self, config: AppConfig, logger: ILoggingProvider) -> None:
        self._logger = logger
        self._logger.info(f"Initializing ChromaDB at: {config.chroma_persist_path}")

        self._client = chromadb.PersistentClient(path=config.chroma_persist_path)

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


