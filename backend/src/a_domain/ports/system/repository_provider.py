from typing import Protocol

from backend.src.a_domain.model.chat.conversation import Conversation


class IRepositoryProvider(Protocol):
    async def get_conversation_by_user_id(
        self, user_id: str
    ) -> Conversation | None: ...
    async def save(self, conversation: Conversation) -> bool: ...


