from datetime import UTC, datetime
from typing import override

import httpx
from openai import AsyncOpenAI, OpenAIError
from openai.types.chat import ChatCompletionMessageParam

from a_domain.model.chat.message import Message, MessageRole
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import AiProvider
from b_application.config.app_config import AppConfig
from c_infrastructure.ai_models.base import BaseAIAdapter


class OpenAIAdapter(BaseAIAdapter):
    """OpenAI's chat API, or a provider's copy of it at base_url, such as Groq's or NVIDIA's."""

    def __init__(
        self,
        config: AppConfig,
        logger: ILoggingProvider,
        model_name: str,
        provider: AiProvider,
        api_key: str | None,
        base_url: str | None = None,
    ):
        if not api_key:
            raise ValueError(f"Missing the {provider.label} API key in configuration.")

        super().__init__(config, logger, model_name)
        self._provider = provider
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=httpx.Timeout(config.ai.connection_timeout))

    @override
    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        """
        The model's streamed reply. An API error, or a network failure before or during the stream, becomes an apology
        the user can read; any other error raises, and the caller records it with its cause.
        """
        api_messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": message.content}
            if message.role == MessageRole.SYSTEM
            else {"role": "user", "content": message.content}
            if message.role == MessageRole.USER
            else {"role": "assistant", "content": message.content}
            for message in messages
        ]
        self._logger.debug(f"[{self._provider.label}] Generating reply with model {self._model_name} from {len(messages)} messages.")

        try:
            stream = await self._client.chat.completions.create(
                model=self._model_name, messages=api_messages, temperature=self._config.ai.temperature, stream=True
            )
            content = "".join([chunk.choices[0].delta.content or "" async for chunk in stream])
        except (OpenAIError, httpx.HTTPError) as error:
            self._logger.error(f"{self._provider.label} API error for model {self._model_name}: {error}")
            content = f"I'm sorry, I'm having trouble connecting to {self._provider.label} right now. Please try again in a moment."

        return Message(role=MessageRole.ASSISTANT, content=content, timestamp=datetime.now(UTC))
