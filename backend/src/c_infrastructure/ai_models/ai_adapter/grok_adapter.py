import time
from datetime import UTC, datetime
from typing import Any, override

import httpx
from openai import AsyncOpenAI, OpenAIError

from a_domain.model.chat.message import Message, MessageRole
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.config.app_config import AppConfig
from c_infrastructure.ai_models.base import BaseAIAdapter


class GrokAdapter(BaseAIAdapter):
    """xAI Grok through its OpenAI-compatible API, with live search and inline citations when the settings turn them on."""

    def __init__(self, config: AppConfig, logger: ILoggingProvider, model_name: str) -> None:
        if not config.ai.grok_api_key:
            raise ValueError("Missing grok_api_key in configuration.")

        super().__init__(config, logger, model_name)
        self._client = AsyncOpenAI(
            api_key=config.ai.grok_api_key,
            base_url=config.sources.ai.grok_base_url,
            timeout=httpx.Timeout(config.ai.connection_timeout),
        )
        self._request_options: dict[str, Any] = {"model": model_name, "temperature": config.ai.temperature, "stream": True}

        if config.behavior.enable_web_search or config.behavior.enable_x_search:
            self._request_options["tools"] = [{"type": "live_search"}]

        if config.behavior.enable_inline_citations:
            self._request_options["extra_body"] = {"include": ["inline_citations"]}

    @override
    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        """The model's streamed reply. An API or network failure raises RuntimeError."""
        messages_option = [{"role": message.role.value, "content": message.content} for message in messages]
        request: dict[str, Any] = {"messages": messages_option, **self._request_options}
        started_at = time.perf_counter()
        self._logger.debug(f"Calling Grok chat completions: model={self._model_name}, messages={len(messages)}, stream=True")

        try:
            stream = await self._client.chat.completions.create(**request)
            self._logger.debug(f"Grok stream opened after {time.perf_counter() - started_at:.1f}s")
            content = ""

            async for chunk in stream:
                delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if delta and not content:
                    self._logger.debug(f"Grok first content token after {time.perf_counter() - started_at:.1f}s")
                content += delta
        except (OpenAIError, httpx.HTTPError) as error:
            self._logger.error(f"Grok API error for model {self._model_name}: {error}")
            raise RuntimeError(f"Grok API request failed for model {self._model_name}: {error}") from error
        except Exception as error:
            self._logger.exception(f"Unexpected error in Grok adapter for model {self._model_name}: {error}")
            raise

        self._logger.debug(f"Grok stream completed after {time.perf_counter() - started_at:.1f}s; chars={len(content)}")

        return Message(role=MessageRole.ASSISTANT, content=content, timestamp=datetime.now(UTC))
