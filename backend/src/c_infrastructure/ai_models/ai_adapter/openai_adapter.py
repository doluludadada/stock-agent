from datetime import UTC, datetime
from typing import override

import httpx
from icontract import require
from openai import AsyncOpenAI, OpenAIError
from openai.types.chat import ChatCompletionMessageParam

from a_domain.model.chat.message import Message, MessageRole
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.config.app_config import AppConfig
from c_infrastructure.ai_models.base import BaseAIAdapter


class OpenAIAdapter(BaseAIAdapter):
    @require(lambda config: bool(config.ai.openai_api_key), "Missing openai_api_key in configuration.")
    def __init__(self, config: AppConfig, logger: ILoggingProvider, model_name: str):
        super().__init__(config, logger, model_name)
        self._client = AsyncOpenAI(api_key=config.ai.openai_api_key, timeout=httpx.Timeout(config.ai.connection_timeout))

    @override
    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        """The model's streamed reply. An OpenAI API error becomes an apology the user can read."""
        api_messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": message.content}
            if message.role == MessageRole.SYSTEM
            else {"role": "user", "content": message.content}
            if message.role == MessageRole.USER
            else {"role": "assistant", "content": message.content}
            for message in messages
        ]
        self._logger.debug(f"[OpenAIAdapter] Generating reply with model {self._model_name} from {len(messages)} messages.")

        try:
            stream = await self._client.chat.completions.create(
                model=self._model_name, messages=api_messages, temperature=self._config.ai.temperature, stream=True
            )
            content = "".join([chunk.choices[0].delta.content or "" async for chunk in stream])
        except OpenAIError as error:
            self._logger.error(f"OpenAI API error for model {self._model_name}: {error}")
            content = "I'm sorry, I'm having trouble connecting to OpenAI right now. Please try again in a moment."

        return Message(role=MessageRole.ASSISTANT, content=content, timestamp=datetime.now(UTC))
