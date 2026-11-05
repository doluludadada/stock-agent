from a_domain.model.chat.conversation import Conversation
from a_domain.model.chat.message import Message
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.chat.chat_styler_provider import IChatStylerProvider
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import MessageRole
from b_application.config.app_config import AppConfig


class ChatReply:
    """
    Answers one chat message of a user and returns the replies to send. The conversation is the user's saved one, or a
    new one that starts with the system prompt. A reset command (chat.reset_commands) saves it with no messages at all
    and answers chat.reset_reply, which is not saved. Any other text joins the conversation, the AI answers it, and the
    conversation is saved with the answer; a failed AI call answers nothing.
    """

    def __init__(
        self,
        ai_provider: IAiProvider,
        chat_styler_provider: IChatStylerProvider,
        conversation_repository: IConversationRepository,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._ai_provider = ai_provider
        self._chat_styler_provider = chat_styler_provider
        self._conversation_repository = conversation_repository
        self._market_clock = market_clock
        self._system_prompt = config.ai.system_prompt
        self._reset_commands = frozenset(config.chat.reset_commands)
        self._reset_reply = config.chat.reset_reply
        self._logger = logger

    async def execute(self, user_id: str, content: str) -> tuple[Message, ...]:
        conversation = await self._conversation_repository.get_conversation_by_user_id(user_id)

        if conversation is None:
            self._logger.info(f"Creating new conversation context for user_id: {user_id}")
            created_at = self._market_clock.now()
            system = (
                [Message(role=MessageRole.SYSTEM, content=self._system_prompt, timestamp=created_at)] if self._system_prompt else []
            )
            conversation = Conversation(user_id=user_id, messages=tuple(system), created_at=created_at, updated_at=created_at)

        now = self._market_clock.now()

        if content.strip() in self._reset_commands:
            await self._conversation_repository.save(conversation.clear_history(now=now))
            self._logger.info(f"Conversation memory cleared for user_id: {user_id}")
            return (Message(role=MessageRole.ASSISTANT, content=self._reset_reply, timestamp=now),)

        conversation = conversation.add_messages([Message(role=MessageRole.USER, content=content, timestamp=now)], now=now)

        try:
            replies = self._chat_styler_provider.format_response(
                await self._ai_provider.generate_reply(messages=conversation.messages)
            )
        except Exception as error:
            self._logger.error(f"Error during AI processing: {error}")
            replies = ()

        await self._conversation_repository.save(conversation.add_messages(replies, now=self._market_clock.now()))
        return replies
