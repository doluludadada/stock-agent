from a_domain.model.chat.conversation import Conversation
from a_domain.model.chat.message import Message
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.system.logging_provider import ILoggingProvider


# class AiProcessor:
#     def __init__(self, ai_port: IAiProvider, styler_port: IChatStylerProvider, logger: ILoggingProvider):
#         self._ai_port = ai_port
#         self._styler_port = styler_port
#         self._logger = logger

#     async def execute(self, conversation: Conversation) -> tuple[Message, ...]:
#         self._logger.debug("Generating AI reply...")
#         try:
#             raw_response = await self._ai_port.generate_reply(messages=conversation.messages)
#             styled_messages = self._styler_port.format_response(raw_response)
#             return styled_messages
#         except Exception as e:
#             self._logger.error(f"Error during AI processing: {e}")
#             return ()


