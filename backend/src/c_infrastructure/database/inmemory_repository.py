# Note: This file will be replaced later
from a_domain.model.chat.conversation import Conversation
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.system.logging_provider import ILoggingProvider


class InMemoryRepositoryAdapter(IConversationRepository):

    _store: dict[str, Conversation] = {}

    def __init__(self, logger: ILoggingProvider):
        self._logger = logger
        self._logger.warning("Using InMemoryRepositoryAdapter. Data is not persistent.")

    async def get_conversation_by_user_id(self, user_id: str) -> Conversation | None:
        self._logger.debug(f"Searching for conversation for user_id: {user_id} in memory.")
        return self._store.get(user_id)

    async def save(self, conversation: Conversation) -> bool:
        self._logger.debug(f"Saving conversation for user_id: {conversation.user_id} in memory.")
        self._store[conversation.user_id] = conversation
        return True


