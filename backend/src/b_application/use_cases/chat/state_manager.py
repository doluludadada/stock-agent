from dataclasses import replace

from a_domain.model.chat.conversation import Conversation
from a_domain.model.chat.message import Message
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock


class StateManager:
    def __init__(self, repository: IConversationRepository, market_clock: IMarketClock, logger: ILoggingProvider):
        self._repository = repository
        self._market_clock = market_clock
        self._logger = logger

    def update_state(self, conversation: Conversation, new_messages: list[Message]) -> Conversation:
        if not new_messages:
            return conversation

        updated_msgs = conversation.messages + tuple(new_messages)
        updated_conversation = replace(conversation, messages=updated_msgs, updated_at=self._market_clock.now())
        return updated_conversation

    async def reset_conversation(self, conversation: Conversation):
        cleared_conversation = conversation.clear_history(now=self._market_clock.now())
        await self._repository.save(cleared_conversation)
        self._logger.info(f"Conversation memory cleared for user_id: {conversation.user_id}")
        return cleared_conversation

    async def save(self, conversation: Conversation) -> None:
        await self._repository.save(conversation)
        self._logger.debug(f"Conversation state saved for user_id: {conversation.user_id}")
