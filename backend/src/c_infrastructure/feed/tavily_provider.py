from typing import Any, override

import httpx

from a_domain.model.chat.web_search_result import WebSearchResult
from a_domain.ports.chat.web_search_provider import IWebSearchProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.config.app_config import AppConfig


class TavilySearchAdapter(IWebSearchProvider):
    """
    Tavily web search adapter.
    """

    def __init__(self, config: AppConfig, logger: ILoggingProvider) -> None:
        if not config.tavily.api_key:
            raise ValueError("Missing tavily_api_key in configuration.")

        self._search_url = config.sources.ai.tavily_search_url
        self._logger = logger
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(config.tavily.connection_timeout))
        self._search_options: dict[str, Any] = {
            "api_key": config.tavily.api_key,
            "search_depth": config.tavily.search_depth,
            "include_answer": False,
            "include_raw_content": False,
        }

        if config.behavior.web_search_allowed_domains:
            self._search_options["include_domains"] = list(config.behavior.web_search_allowed_domains)

        if config.behavior.web_search_excluded_domains:
            self._search_options["exclude_domains"] = list(config.behavior.web_search_excluded_domains)

    @override
    async def search(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        payload = {"query": query, "max_results": limit, **self._search_options}

        try:
            response = await self._client.post(self._search_url, json=payload)
            response.raise_for_status()

            return [
                WebSearchResult(
                    title=(item.get("title") or "").strip(),
                    url=(item.get("url") or "").strip(),
                    content=(item.get("content") or item.get("snippet") or "").strip(),
                )
                for item in (response.json().get("results") or [])[:limit]
            ]
        except Exception as error:
            self._logger.error(f"[TavilySearchAdapter] search failed: {error}")
            return []
