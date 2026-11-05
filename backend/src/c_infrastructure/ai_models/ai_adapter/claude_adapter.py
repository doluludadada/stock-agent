from datetime import UTC, datetime
from typing import override

import anthropic
from anthropic import AsyncAnthropic, omit
from anthropic.types import AssistantMessageParam, MessageParam, UserMessageParam

from a_domain.model.chat.message import Message, MessageRole
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.config.app_config import AppConfig
from c_infrastructure.ai_models.base import BaseAIAdapter


class ClaudeAdapter(BaseAIAdapter):
    """
    Claude through Anthropic's Messages API. System messages become the request's system prompt and the reply is the
    text of the streamed final message. Current Claude models refuse a temperature setting, so ai.temperature is not
    sent; ai.max_output_tokens caps the reply, its thinking included.
    """

    def __init__(self, config: AppConfig, logger: ILoggingProvider, model_name: str) -> None:
        if not config.ai.anthropic_api_key:
            raise ValueError("Missing the Claude API key (ANTHROPIC_API_KEY) in configuration.")

        super().__init__(config, logger, model_name)
        self._client = AsyncAnthropic(api_key=config.ai.anthropic_api_key, timeout=config.ai.connection_timeout)

    @override
    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        """The model's reply. An API error or a refusal becomes an apology the user can read."""
        system = "\n\n".join(message.content for message in messages if message.role == MessageRole.SYSTEM)
        conversation: list[MessageParam] = [
            UserMessageParam(role="user", content=message.content)
            if message.role == MessageRole.USER
            else AssistantMessageParam(role="assistant", content=message.content)
            for message in messages
            if message.role != MessageRole.SYSTEM
        ]
        self._logger.debug(f"[Claude] Generating reply with model {self._model_name} from {len(messages)} messages.")

        try:
            async with self._client.messages.stream(
                model=self._model_name, max_tokens=self._config.ai.max_output_tokens, system=system or omit, messages=conversation
            ) as stream:
                reply = await stream.get_final_message()

            content = "".join(block.text for block in reply.content if block.type == "text")

            if reply.stop_reason == "refusal":
                self._logger.error(f"Claude declined the request (request {reply._request_id}).")
                content = "I'm sorry, Claude declined to answer this request."
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as error:
            self._logger.error(f"Claude API error for model {self._model_name}: {type(error).__name__}: {error}")
            content = "I'm sorry, I'm having trouble connecting to Claude right now. Please try again in a moment."

        return Message(role=MessageRole.ASSISTANT, content=content, timestamp=datetime.now(UTC))
