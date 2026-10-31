from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from support.harness import build_harness, rising_history

from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.config.sources_config import SourcesConfig
from c_infrastructure.ai_models.ai_adapter.grok_adapter import GrokAdapter
from c_infrastructure.feed.news.cnyes_news_provider import CnyesNewsProvider

SOURCES = SourcesConfig()


class FakeLogger(ILoggingProvider):
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def info(self, message: str):
        self.messages.append(message)

    def warning(self, message: str):
        self.warnings.append(message)
        self.messages.append(message)

    def debug(self, message: str):
        self.messages.append(message)

    def critical(self, message: str):
        self.messages.append(message)

    def error(self, message: str):
        self.errors.append(message)
        self.messages.append(message)

    def success(self, message: str):
        self.messages.append(message)

    def trace(self, message: str):
        self.messages.append(message)

    def exception(self, message: str):
        self.messages.append(message)


class FailingCompletions:
    async def create(self, **params):
        raise httpx.ConnectTimeout("timed out")


class FakeClient:
    chat = SimpleNamespace(completions=FailingCompletions())


class FakeCnyesResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.request = httpx.Request("GET", "https://api.cnyes.com/media/api/v1/search")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = httpx.Response(self.status_code, request=self.request)
            raise httpx.HTTPStatusError("server error", request=self.request, response=response)

    def json(self) -> dict:
        return self._payload


class SymbolNewsCnyesClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, *args, **kwargs) -> FakeCnyesResponse:
        if url == "https://news.cnyes.com/news/id/2":
            return FakeCnyesResponse(200, text='<html><div id="article-container"><p>2486 matched content</p></div></html>')
        if "TWS:2486:STOCK/symbolNews" not in url:
            raise AssertionError(f"Unexpected Cnyes URL: {url}")
        # symbolNews lists headlines only; the body lives on the article page.
        return FakeCnyesResponse(200, {"items": {"data": [{"newsId": 2, "title": "一詮測試新聞", "publishAt": 1778489049}]}})


@pytest.mark.asyncio
async def test_cnyes_fetches_symbol_news(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", SymbolNewsCnyesClient)
    logger = FakeLogger()
    provider = CnyesNewsProvider(SOURCES.news, logger)

    articles = await provider.fetch_news("2486", limit=10)

    assert len(articles) == 1
    assert articles[0].title == "一詮測試新聞"
    assert articles[0].content == "2486 matched content"
    assert logger.errors == []
    assert logger.warnings == []


@pytest.mark.asyncio
async def test_ai_analyser_records_provider_failure_without_counting_success() -> None:
    harness = build_harness()
    harness.list_stock("2486", rising_history(100.0), realtime_price=100.0)
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.ai.failures["2486"] = RuntimeError("provider is unavailable")

    status = await harness.run_menu("4", stock_ids="2486 2330")

    failed, analysed = status.manual_stocks
    assert status.stats.ai_analysed == 1
    [error] = status.stats.errors
    assert "2486" in error
    assert "provider is unavailable" in error
    assert (failed.ai_score, failed.composite_score) == (None, None)
    assert analysed.ai_score == harness.ai.default_score


@pytest.mark.asyncio
async def test_grok_adapter_raises_on_http_failure() -> None:
    config = SimpleNamespace(
        ai=SimpleNamespace(grok_api_key="test-key", connection_timeout=1),
        sources=SOURCES,
        behavior=SimpleNamespace(enable_web_search=False, enable_x_search=False, enable_inline_citations=False),
    )
    adapter = GrokAdapter(config=cast(Any, config), logger=FakeLogger(), model_name="grok-test")
    vars(adapter)["_client"] = FakeClient()

    with pytest.raises(RuntimeError, match="Grok API request failed"):
        await adapter._call_api(())
