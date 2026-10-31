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


class GroqAIAdapter(BaseAIAdapter):
    """Groq (GroqCloud) through its OpenAI-compatible API."""

    @require(lambda config: bool(config.ai.groq_api_key), "Missing groq_api_key in configuration.")
    def __init__(self, config: AppConfig, logger: ILoggingProvider, model_name: str):
        super().__init__(config, logger, model_name)
        self._client = AsyncOpenAI(
            api_key=config.ai.groq_api_key,
            base_url=config.sources.ai.groq_base_url,
            timeout=httpx.Timeout(config.ai.connection_timeout),
        )

    @override
    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        """The model's streamed reply. Any failure becomes an apology the user can read."""
        api_messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": message.content}
            if message.role == MessageRole.SYSTEM
            else {"role": "user", "content": message.content}
            if message.role == MessageRole.USER
            else {"role": "assistant", "content": message.content}
            for message in messages
        ]
        self._logger.debug(f"[GroqAIAdapter] Generating reply with model {self._model_name} from {len(messages)} messages.")

        try:
            stream = await self._client.chat.completions.create(
                model=self._model_name, messages=api_messages, temperature=self._config.ai.temperature, stream=True
            )
            content = "".join([chunk.choices[0].delta.content or "" async for chunk in stream])
        except (OpenAIError, httpx.HTTPError) as error:
            self._logger.error(f"GROQ API error for model {self._model_name}: {error}")
            content = "I'm sorry, I'm having trouble connecting right now. Please try again in a moment."
        except Exception as error:
            self._logger.error(f"Unexpected error calling GROQ ({self._model_name}): {error}")
            content = "I'm sorry, something went wrong. Please try again."

        return Message(role=MessageRole.ASSISTANT, content=content, timestamp=datetime.now(UTC))
