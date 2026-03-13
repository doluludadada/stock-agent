import httpx

from a_domain.model.chat.web_search_result import WebSearchResult
from a_domain.ports.chat.web_search_provider import IWebSearchProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.config import AppConfig


class TavilySearchAdapter(IWebSearchProvider):
    """
    Tavily web search adapter.
    """

    def __init__(self, config: AppConfig, logger: ILoggingProvider) -> None:
        self._config = config
        self._logger = logger

        if not self._config.tavily.api_key:
            raise ValueError("Missing tavily_api_key in configuration.")

        timeout = getattr(self._config, "ai_model_connection_timeout", 30)
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))

    async def search(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        payload: dict = {
            "api_key": self._config.tavily.api_key,
            "query": query,
            "max_results": limit,
            "search_depth": self._config.tavily.search_depth,  # "basic" | "advanced"
            "include_answer": False,
            "include_raw_content": False,
        }

        allowed = self._config.behavior.web_search_allowed_domains
        excluded = self._config.behavior.web_search_excluded_domains

        if allowed:
            payload["include_domains"] = list(allowed)
        if excluded:
            payload["exclude_domains"] = list(excluded)

        try:
            resp = await self._client.post("https://api.tavily.com/search", json=payload)
            resp.raise_for_status()
            data = resp.json()

            results: list[WebSearchResult] = []
            for item in (data.get("results") or [])[:limit]:
                results.append(
                    WebSearchResult(
                        title=(item.get("title") or "").strip(),
                        url=(item.get("url") or "").strip(),
                        content=(item.get("content") or item.get("snippet") or "").strip(),
                    )
                )
            return results

        except Exception as e:
            self._logger.error(f"[TavilySearchAdapter] search failed: {e}")
            return []


