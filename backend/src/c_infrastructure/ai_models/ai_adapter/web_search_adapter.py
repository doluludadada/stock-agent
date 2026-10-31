from typing import override

from a_domain.model.chat.message import Message, MessageRole
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.chat.web_search_provider import IWebSearchProvider
from a_domain.ports.system.logging_provider import ILoggingProvider


class WebSearchAiAdapter(IAiProvider):
    """
    Searches the web before another AI provider replies, when the user's last message holds a trigger word, and gives
    the model the results as a system message just before that message. A failed or empty search only skips the results.
    """

    def __init__(
        self,
        ai_provider: IAiProvider,
        web_search_provider: IWebSearchProvider,
        triggers: frozenset[str],
        max_results: int,
        results_prompt: str,
        logger: ILoggingProvider,
    ) -> None:
        self._ai_provider = ai_provider
        self._web_search_provider = web_search_provider
        self._triggers = triggers
        self._max_results = max_results
        self._results_prompt = results_prompt
        self._logger = logger

    @override
    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        query = next((message.content for message in reversed(messages) if message.role == MessageRole.USER), "")

        if not any(trigger in query.lower() for trigger in self._triggers):
            return await self._ai_provider.generate_reply(messages)

        try:
            self._logger.debug(f"Searching the web for the user's last message ({len(query)} characters).")
            results = await self._web_search_provider.search(query, limit=self._max_results)
        except Exception as error:
            self._logger.error(f"Search enrichment failed, proceeding without: {error}")
            return await self._ai_provider.generate_reply(messages)

        if not results:
            return await self._ai_provider.generate_reply(messages)

        found = "".join(
            f"\n[{index}] {result.title}\nURL: {result.url}\nContent: {result.content}\n" for index, result in enumerate(results, 1)
        )
        content = self._results_prompt.format(search_results=f"Recent web search results:\n{found}")
        instruction = Message(role=MessageRole.SYSTEM, content=content, timestamp=messages[-1].timestamp)
        enriched = (*messages[:-1], instruction, messages[-1]) if messages[-1].role == MessageRole.USER else (*messages, instruction)

        return await self._ai_provider.generate_reply(enriched)

    @override
    def save_response(self, stock_id: str, content: str) -> None:
        self._ai_provider.save_response(stock_id, content)
