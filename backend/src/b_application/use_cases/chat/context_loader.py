from a_domain.model.chat.conversation import Conversation
from a_domain.model.chat.message import Message, MessageRole
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from b_application.config.app_config import AppConfig


class ContextLoader:
    def __init__(self, repository: IConversationRepository, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider):
        self._repository = repository
        self._market_clock = market_clock
        self._config = config
        self._logger = logger

    async def execute(self, user_id: str) -> Conversation:
        conversation = await self._repository.get_conversation_by_user_id(user_id)
        if conversation:
            self._logger.debug(f"Found existing conversation for user_id: {user_id}")
            return conversation

        self._logger.info(f"Creating new conversation context for user_id: {user_id}")
        now = self._market_clock.now()
        initial_messages = []
        if self._config.ai.system_prompt:
            initial_messages.append(Message(role=MessageRole.SYSTEM, content=self._config.ai.system_prompt, timestamp=now))
        return Conversation(user_id=user_id, messages=tuple(initial_messages), created_at=now, updated_at=now)
