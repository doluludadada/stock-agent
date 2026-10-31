import asyncio
from functools import cached_property
from typing import Any

from google.generativeai.client import configure
from google.generativeai.generative_models import GenerativeModel
from icontract import require

from a_domain.model.chat.message import Message, MessageRole
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.config.app_config import AppConfig
from c_infrastructure.ai_models.base import BaseAIAdapter


class GeminiAIAdapter(BaseAIAdapter):
    @require(lambda config: bool(config.ai.gemini_api_key), "Missing gemini_api_key in configuration.")
    def __init__(self, config: AppConfig, logger: ILoggingProvider, model_name: str) -> None:
        super().__init__(config, logger, model_name)
        configure(api_key=self._config.ai.gemini_api_key)

    @cached_property
    def _client(self) -> Any:
        self._logger.debug(f"[{self.__class__.__name__}] Creating GenerativeModel for: {self._model_name}")
        return GenerativeModel(self._model_name)

    async def _call_api(self, messages: tuple[Message, ...]) -> str:
        prompt = self._convert_to_prompt(messages)
        self._logger.debug(f"[{self.__class__.__name__}] Calling Gemini, prompt length={len(prompt)}")
        try:
            response = await asyncio.to_thread(lambda: self._client.generate_content(prompt, generation_config={"temperature": 0.7}))
        except Exception as error:
            self._logger.error(f"[{self.__class__.__name__}] Gemini API call failed: {error}")
            raise
        text = self._extract_text_from_response(response)
        return text

    def _convert_to_prompt(self, messages: tuple[Message, ...]) -> str:
        lines: list[str] = []
        for message in messages:
            if message.role == MessageRole.SYSTEM:
                prefix = "[system]"
            elif message.role == MessageRole.USER:
                prefix = "[user]"
            else:
                prefix = "[assistant]"
            lines.append(f"{prefix} {message.content}")
        return "\n".join(lines)

    def _extract_text_from_response(self, resp: Any) -> str:
        try:
            text = getattr(resp, "text", None)
            if isinstance(text, str) and text.strip():
                return text
            candidates = getattr(resp, "candidates", None)
            if candidates:
                first = candidates[0]
                content = getattr(first, "content", None) or getattr(first, "output", None)
                if content is not None:
                    parts = getattr(content, "parts", None)
                    if parts:
                        texts: list[str] = []
                        for part in parts:
                            part_text = getattr(part, "text", None)
                            if isinstance(part_text, str) and part_text.strip():
                                texts.append(part_text)
                        if texts:
                            return "\n".join(texts)
            if isinstance(resp, dict):
                text = resp.get("text")
                if isinstance(text, str) and text.strip():
                    return text
                out = resp.get("output")
                if isinstance(out, str) and out.strip():
                    return out
            return str(resp)
        except Exception as error:
            self._logger.error(f"[{self.__class__.__name__}] Failed to parse Gemini response, falling back to str(resp): {error}")
            return str(resp)
