from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

from a_domain.model.market.article import Article
from a_domain.model.market.stock import Stock
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.process.ai.parser import AiReportParser
from a_domain.rules.process.ai.prompt import AiReportPromptBuilder
from a_domain.types.enums import InformationSource
from b_application.schemas.pipeline_context import PipelineContext
from b_application.use_cases.process.ai_analyser import AiAnalyser
from c_infrastructure.ai_models.ai_adapter.grok_adapter import GrokAdapter
from c_infrastructure.feed.news.cnyes_news_provider import CnyesNewsProvider


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


class FailingAiProvider:
    async def generate_reply(self, messages):
        raise RuntimeError("provider is unavailable")

    def save_response(self, stock_id: str, content: str) -> None:
        raise AssertionError("save_response should not be called after provider failure")


class EmptyKnowledgeRepository:
    async def search(self, stock_id: str) -> str:
        return ""


class FailingCompletions:
    async def create(self, **params):
        raise httpx.ConnectTimeout("timed out")


class FakeClient:
    chat = SimpleNamespace(completions=FailingCompletions())


class FakeCnyesResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
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
        if "TWS:2486:STOCK/symbolNews" not in url:
            raise AssertionError(f"Unexpected Cnyes URL: {url}")
        return FakeCnyesResponse(
            200,
            {
                "items": {
                    "data": [
                        {
                            "newsId": 2,
                            "title": "一詮測試新聞",
                            "summary": "一詮 symbol news article",
                            "content": "<p>2486 matched content</p>",
                            "publishAt": 1778489049,
                        },
                    ]
                }
            },
        )


@pytest.mark.asyncio
async def test_cnyes_fetches_symbol_news(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", SymbolNewsCnyesClient)
    logger = FakeLogger()
    provider = CnyesNewsProvider(logger)

    articles = await provider.fetch_news("2486", limit=10)

    assert len(articles) == 1
    assert articles[0].title == "一詮測試新聞"
    assert articles[0].content == "2486 matched content"
    assert logger.errors == []
    assert logger.warnings == []


@pytest.mark.asyncio
async def test_ai_analyser_records_provider_failure_without_counting_success() -> None:
    stock = Stock(stock_id="2486")
    stock.articles = [
        Article(
            stock_id="2486",
            source=InformationSource.NEWS_MEDIA,
            title="Test article",
            content="A long enough article body for the prompt builder.",
            published_at=datetime(2026, 5, 11),
        )
    ]
    context = PipelineContext(survivors=[stock])

    analyser = AiAnalyser(
        ai_provider=FailingAiProvider(),
        prompt_builder=AiReportPromptBuilder(
            fundamental_template="Analyze {stock_id}: {articles_text}",
            momentum_template="Analyze {stock_id}: {articles_text}",
            max_articles=10,
            max_content_length=500,
        ),
        response_parser=AiReportParser(),
        knowledge_repo=EmptyKnowledgeRepository(),
        config=SimpleNamespace(),
        logger=FakeLogger(),
    )

    await analyser.execute(context)

    assert context.stats.ai_analysed == 0
    assert context.stats.total_errors == 1
    assert "provider is unavailable" in context.stats.errors[0]
    assert stock.ai_score == 50


@pytest.mark.asyncio
async def test_grok_adapter_raises_on_http_failure() -> None:
    config = SimpleNamespace(
        ai=SimpleNamespace(grok_api_key="test-key", connection_timeout=1),
        behavior=SimpleNamespace(enable_web_search=False, enable_x_search=False, enable_inline_citations=False),
    )
    adapter = GrokAdapter(config=config, logger=FakeLogger(), model_name="grok-test")
    adapter.__dict__["_client"] = FakeClient()

    with pytest.raises(RuntimeError, match="Grok API request failed"):
        await adapter._call_api(())
