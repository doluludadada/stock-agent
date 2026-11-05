import asyncio
from datetime import UTC, datetime
from typing import override

from google.generativeai.client import configure
from google.generativeai.generative_models import GenerativeModel

from a_domain.model.chat.message import Message, MessageRole
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.config.app_config import AppConfig
from c_infrastructure.ai_models.base import BaseAIAdapter


class GeminiAIAdapter(BaseAIAdapter):
    def __init__(self, config: AppConfig, logger: ILoggingProvider, model_name: str) -> None:
        if not config.ai.gemini_api_key:
            raise ValueError("Missing gemini_api_key in configuration.")

        super().__init__(config, logger, model_name)
        configure(api_key=config.ai.gemini_api_key)
        self._model = GenerativeModel(model_name)

    @override
    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        """The model's reply to the conversation sent as one prompt. A reply without text is returned as Gemini printed it."""
        prompt = "\n".join(f"[{message.role.value}] {message.content}" for message in messages)
        self._logger.debug(f"[GeminiAIAdapter] Calling Gemini, prompt length={len(prompt)}")

        try:
            response = await asyncio.to_thread(
                self._model.generate_content, prompt, generation_config={"temperature": self._config.ai.temperature}
            )
        except Exception as error:
            self._logger.error(f"[GeminiAIAdapter] Gemini API call failed: {error}")
            raise

        try:
            text = response.text
        except Exception as error:
            self._logger.error(f"[GeminiAIAdapter] Gemini reply has no text, falling back to the whole response: {error}")
            text = ""

        return Message(role=MessageRole.ASSISTANT, content=text if text.strip() else str(response), timestamp=datetime.now(UTC))
