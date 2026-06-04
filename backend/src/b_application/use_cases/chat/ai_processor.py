from a_domain.model.chat.conversation import Conversation
from a_domain.model.chat.message import Message
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.chat.chat_styler_provider import IChatStylerProvider
from a_domain.ports.system.logging_provider import ILoggingProvider


class AiProcessor:
    def __init__(
        self,
        ai_provider: IAiProvider,
        chat_styler_provider: IChatStylerProvider,
        logger: ILoggingProvider,
    ):
        self._ai_provider = ai_provider
        self._chat_styler_provider = chat_styler_provider
        self._logger = logger

    async def execute(self, conversation: Conversation) -> tuple[Message, ...]:
        self._logger.debug("Generating AI reply...")
        try:
            raw_response = await self._ai_provider.generate_reply(messages=conversation.messages)
            styled_messages = self._chat_styler_provider.format_response(raw_response)
            return styled_messages
        except Exception as e:
            self._logger.error(f"Error during AI processing: {e}")
            return ()
