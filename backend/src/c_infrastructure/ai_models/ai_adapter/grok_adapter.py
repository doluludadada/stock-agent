import asyncio
import time
from functools import cached_property
from typing import Any

import httpx
from openai import AsyncOpenAI, OpenAIError

from a_domain.model.chat.message import Message, MessageRole
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.config import AppConfig
from c_infrastructure.ai_models.base import BaseAIAdapter


class GrokAdapter(BaseAIAdapter):
    def __init__(self, config: AppConfig, logger: ILoggingProvider, model_name: str):
        super().__init__(config, logger, model_name)
        if not self._config.ai.grok_api_key:
            raise ValueError("Missing grok_api_key in configuration.")

    @cached_property
    def _client(self) -> AsyncOpenAI:
        self._logger.debug("Initializing Grok client (xAI)...")
        return AsyncOpenAI(
            api_key=self._config.ai.grok_api_key,
            base_url="https://api.x.ai/v1",
            timeout=httpx.Timeout(self._config.ai.connection_timeout),
        )

    async def _call_api(self, messages: tuple[Message, ...]) -> str:
        api_messages = self._convert_to_api_format(messages)
        tools: list[dict[str, Any]] = []

        if self._config.behavior.enable_web_search or self._config.behavior.enable_x_search:
            tools.append({"type": "live_search"})

        extra_body: dict[str, Any] = {}

        if self._config.behavior.enable_inline_citations:
            extra_body["include"] = ["inline_citations"]

        try:
            params: dict[str, Any] = {
                "model": self._model_name,
                "messages": api_messages,
                "temperature": 0.7,
                "stream": True,
            }

            # In the OpenAI SDK, tools are a top-level parameter
            if tools:
                params["tools"] = tools

            if extra_body:
                params["extra_body"] = extra_body

            started_at = time.perf_counter()
            self._logger.debug(f"Calling Grok chat completions: model={self._model_name}, messages={len(api_messages)}, stream=True")
            stream = await self._client.chat.completions.create(**params)
            self._logger.debug(f"Grok stream opened after {time.perf_counter() - started_at:.1f}s")

            full_content = ""
            first_content_seen = False
            async for chunk in stream:
                if not chunk.choices:
                    continue
                content_delta = chunk.choices[0].delta.content or ""
                if content_delta and not first_content_seen:
                    first_content_seen = True
                    self._logger.debug(f"Grok first content token after {time.perf_counter() - started_at:.1f}s")
                full_content += content_delta

            self._logger.debug(f"Grok stream completed after {time.perf_counter() - started_at:.1f}s; chars={len(full_content)}")
            return full_content

        except asyncio.CancelledError:
            raise
        except (OpenAIError, httpx.HTTPError) as e:
            self._logger.error(f"Grok API error for model {self._model_name}: {e}")
            raise RuntimeError(f"Grok API request failed for model {self._model_name}: {e}") from e
        except Exception as e:
            self._logger.exception(f"Unexpected error in Grok adapter for model {self._model_name}: {e}")
            raise

    def _convert_to_api_format(self, messages: tuple[Message, ...]):
        api_messages = []
        for message in messages:
            role = "assistant"
            if message.role == MessageRole.SYSTEM:
                role = "system"
            elif message.role == MessageRole.USER:
                role = "user"
            api_messages.append({"role": role, "content": message.content})
        return api_messages
