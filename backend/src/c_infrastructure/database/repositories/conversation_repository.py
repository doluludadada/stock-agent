from typing import override

from a_domain.model.chat.conversation import Conversation
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.conversation_dto import ConversationDTO


class SqlConversationRepository(IConversationRepository):
    """
    Each chat user's conversation in the chat_conversations table, one row per user id, which a save replaces whole. A
    conversation that cannot be read is logged and read as none, and a save that fails is logged and answers False.
    """

    def __init__(self, db: DatabaseConnector, logger: ILoggingProvider) -> None:
        self._db = db
        self._logger = logger

    @override
    async def get_conversation_by_user_id(self, user_id: str) -> Conversation | None:
        try:
            async with self._db.get_session() as session:
                row = await session.get(ConversationDTO, user_id)

            return row.to_domain() if row is not None else None
        except Exception as error:
            self._logger.error(f"Failed to load conversation for {user_id}: {error}")
            return None

    @override
    async def save(self, conversation: Conversation) -> bool:
        try:
            async with self._db.get_session() as session:
                await session.merge(ConversationDTO.from_domain(conversation))
                await session.commit()
        except Exception as error:
            self._logger.error(f"Failed to save conversation: {error}")
            return False

        return True
