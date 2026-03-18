"""
Groq AI adapter implementation.

Infrastructure layer adapter that calls GroqCloud via OpenAI-compatible API.
"""

import asyncio
from functools import cached_property

import httpx
from openai import AsyncOpenAI, OpenAIError
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

from a_domain.model.chat.message import Message, MessageRole
from a_domain.ports.chat.web_search_provider import IWebSearchProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.config import AppConfig
from c_infrastructure.ai_models.base import BaseAIAdapter


class GroqAIAdapter(BaseAIAdapter):
    """
    Groq (GroqCloud) adapter via OpenAI-compatible API.
    """

    groq_base_url = "https://api.groq.com/openai/v1"

    def __init__(
        self,
        config: AppConfig,
        logger: ILoggingProvider,
        model_name: str = "openai/gpt-oss-20b",
        web_search: IWebSearchProvider | None = None,
    ):
        super().__init__(config, logger, model_name)

        if not self._config.ai.groq_api_key:
            raise ValueError("Missing groq_api_key in configuration.")

        self._web_search = web_search

    @cached_property
    def _client(self) -> AsyncOpenAI:
        self._logger.debug("Initialising AsyncOpenAI client...")
        return AsyncOpenAI(
            api_key=self._config.ai.groq_api_key,
            base_url=self.groq_base_url,
            timeout=httpx.Timeout(self._config.ai.connection_timeout),
        )

    async def _call_api(self, messages: tuple[Message, ...]) -> str:
        api_messages = self._convert_to_api_format(messages)

        # Search enrichment — non-fatal, LLM call always proceeds
        if self._should_search(messages):
            try:
                search_results = await self._enrich_with_search(messages)
                if search_results and self._config.ai.rag_injection_prompt:
                    rag_instruction = {
                        "role": "system",
                        "content": self._config.ai.rag_injection_prompt.format(search_results=search_results),
                    }
                    if api_messages and api_messages[-1]["role"] == "user":
                        api_messages.insert(-1, rag_instruction)  # type: ignore
                    else:
                        api_messages.append(rag_instruction)  # type: ignore
            except Exception as e:
                self._logger.error(f"Search enrichment failed, proceeding without: {e}")

        # LLM call — always runs regardless of search outcome
        try:
            stream = await self._client.chat.completions.create(
                model=self._model_name,
                messages=api_messages,
                temperature=0.7,
                stream=True,
            )

            full_content = ""
            async for chunk in stream:
                content_delta = chunk.choices[0].delta.content or ""
                full_content += content_delta

            return full_content
        except asyncio.CancelledError:
            raise
        except (OpenAIError, httpx.HTTPError) as e:
            self._logger.error(f"GROQ API error for model {self._model_name}: {e}")
            return "I'm sorry, I'm having trouble connecting right now. Please try again in a moment."
        except Exception as e:
            self._logger.error(f"Unexpected error calling GROQ ({self._model_name}): {e}")
            return "I'm sorry, something went wrong. Please try again."

    async def _enrich_with_search(self, messages: tuple[Message, ...]) -> str:
        """Execute web search and format results."""
        if not self._web_search:
            return ""

        user_query = ""
        for msg in reversed(messages):
            if msg.role == MessageRole.USER:
                user_query = msg.content
                break

        if not user_query:
            return ""

        self._logger.debug(f"Performing web search for: {user_query}")
        results = await self._web_search.search(
            user_query,
            limit=self._config.behavior.web_search_max_results,
        )

        if not results:
            return ""

        formatted = "Recent web search results:\n"
        for i, result in enumerate(results, 1):
            formatted += f"\n[{i}] {result.title}\nURL: {result.url}\nContent: {result.content}\n"

        return formatted

    def _should_search(self, messages: tuple[Message, ...]) -> bool:
        """Determine if web search should be triggered."""
        if not self._config.behavior.enable_web_search or not self._web_search:
            return False

        for msg in reversed(messages):
            if msg.role == MessageRole.USER:
                content = msg.content.lower()
                search_triggers = {
                    "latest",
                    "recent",
                    "news",
                    "current",
                    "today",
                    "stock",
                    "weather",
                    "時事",
                    "今天",
                    "最新",
                    "新聞",
                    "查詢",
                }
                return any(t in content for t in search_triggers)

        return False

    def _convert_to_api_format(
        self, messages: tuple[Message, ...]
    ) -> list[ChatCompletionSystemMessageParam | ChatCompletionUserMessageParam | ChatCompletionAssistantMessageParam]:
        api_messages = []
        for message in messages:
            if message.role == MessageRole.SYSTEM:
                api_messages.append(ChatCompletionSystemMessageParam(role="system", content=message.content))
            elif message.role == MessageRole.USER:
                api_messages.append(ChatCompletionUserMessageParam(role="user", content=message.content))
            elif message.role == MessageRole.ASSISTANT:
                api_messages.append(ChatCompletionAssistantMessageParam(role="assistant", content=message.content))
        return api_messages
