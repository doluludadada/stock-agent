"""The OpenAI-compatible AI adapters, the web search step and Tavily, over fake clients."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError
from support.settings import shipped_config

from a_domain.model.chat.message import Message
from a_domain.model.chat.web_search_result import WebSearchResult
from a_domain.types.enums import MessageRole
from b_application.config.ai_config import TavilyConfig
from b_application.config.app_config import AppConfig
from c_infrastructure.ai_models.ai_adapter import groq_adapter, openai_adapter
from c_infrastructure.ai_models.ai_adapter.groq_adapter import GroqAIAdapter
from c_infrastructure.ai_models.ai_adapter.openai_adapter import OpenAIAdapter
from c_infrastructure.ai_models.ai_adapter.web_search_adapter import WebSearchAiAdapter
from c_infrastructure.feed import tavily_provider
from c_infrastructure.feed.tavily_provider import TavilySearchAdapter

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 30, 1, 0, tzinfo=UTC)
CONVERSATION = (
    Message(role=MessageRole.SYSTEM, content="You are an analyst.", timestamp=NOW),
    Message(role=MessageRole.USER, content="How is 2330?", timestamp=NOW),
    Message(role=MessageRole.ASSISTANT, content="It rose.", timestamp=NOW),
    Message(role=MessageRole.USER, content="Why?", timestamp=NOW),
)


class SilentLogger:
    def __getattr__(self, name: str):
        return lambda message: None


def chunk(text: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])


class Stream:
    def __init__(self, texts: list[str]) -> None:
        self._chunks = [chunk(text) for text in texts]

    def __aiter__(self):
        return self

    async def __anext__(self) -> SimpleNamespace:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class RecordingOpenAI:
    """Stands in for openai.AsyncOpenAI: records each chat completion request and streams the scripted reply."""

    requests: list[dict] = []
    reply: list[str] | Exception = []

    def __init__(self, **client_options) -> None:
        self.client_options = client_options
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **params) -> Stream:
        RecordingOpenAI.requests.append(params)

        if isinstance(RecordingOpenAI.reply, Exception):
            raise RecordingOpenAI.reply

        return Stream(RecordingOpenAI.reply)


@pytest.fixture
def openai_client(monkeypatch: pytest.MonkeyPatch) -> type[RecordingOpenAI]:
    RecordingOpenAI.requests = []
    RecordingOpenAI.reply = ["Supply ", "is tight."]
    monkeypatch.setattr(openai_adapter, "AsyncOpenAI", RecordingOpenAI)
    monkeypatch.setattr(groq_adapter, "AsyncOpenAI", RecordingOpenAI)
    return RecordingOpenAI


def config() -> AppConfig:
    shipped = shipped_config()
    keys = {"openai_api_key": "openai-key", "groq_api_key": "groq-key", "temperature": 0.3}
    return shipped.model_copy(update={"ai": shipped.ai.model_copy(update=keys)})


@pytest.mark.parametrize("adapter_class", [OpenAIAdapter, GroqAIAdapter])
async def test_an_openai_compatible_adapter_sends_every_role_and_joins_the_streamed_reply(
    adapter_class: type[OpenAIAdapter] | type[GroqAIAdapter], openai_client: type[RecordingOpenAI]
) -> None:
    adapter = adapter_class(config=config(), logger=SilentLogger(), model_name="test-model")

    reply = await adapter.generate_reply(CONVERSATION)

    assert (reply.role, reply.content) == (MessageRole.ASSISTANT, "Supply is tight.")
    [request] = openai_client.requests
    assert request["messages"] == [{"role": message.role.value, "content": message.content} for message in CONVERSATION]
    assert (request["model"], request["temperature"], request["stream"]) == ("test-model", 0.3, True)


@pytest.mark.parametrize(
    ("adapter_class", "apology"),
    [
        (OpenAIAdapter, "I'm sorry, I'm having trouble connecting to OpenAI right now. Please try again in a moment."),
        (GroqAIAdapter, "I'm sorry, I'm having trouble connecting right now. Please try again in a moment."),
    ],
)
async def test_an_openai_compatible_adapter_answers_a_connection_failure_with_an_apology(
    adapter_class: type[OpenAIAdapter] | type[GroqAIAdapter], apology: str, openai_client: type[RecordingOpenAI]
) -> None:
    openai_client.reply = APIConnectionError(request=httpx.Request("POST", "https://api.example/v1/chat/completions"))
    adapter = adapter_class(config=config(), logger=SilentLogger(), model_name="test-model")

    reply = await adapter.generate_reply(CONVERSATION)

    assert reply.content == apology


class FakeAiProvider:
    def __init__(self) -> None:
        self.conversations: list[tuple[Message, ...]] = []

    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        self.conversations.append(messages)
        return Message(role=MessageRole.ASSISTANT, content="answer", timestamp=NOW)

    def save_response(self, stock_id: str, content: str) -> None:
        return None


class FakeWebSearch:
    def __init__(self, results: list[WebSearchResult] | Exception) -> None:
        self.results = results
        self.queries: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        self.queries.append((query, limit))

        if isinstance(self.results, Exception):
            raise self.results

        return self.results


def web_search_adapter(ai_provider: FakeAiProvider, search: FakeWebSearch) -> WebSearchAiAdapter:
    behavior = shipped_config().behavior.model_copy(update={"web_search_triggers": frozenset({"news"}), "web_search_max_results": 2})
    return WebSearchAiAdapter(
        ai_provider=ai_provider,
        web_search_provider=search,
        triggers=behavior.web_search_triggers,
        max_results=behavior.web_search_max_results,
        results_prompt="Context:\n{search_results}",
        logger=SilentLogger(),
    )


async def test_a_trigger_word_puts_the_search_results_just_before_the_users_message() -> None:
    ai_provider = FakeAiProvider()
    search = FakeWebSearch([WebSearchResult(title="TSMC up", url="https://news/1", content="Revenue beat.")])
    question = Message(role=MessageRole.USER, content="Any NEWS on 2330?", timestamp=NOW)

    reply = await web_search_adapter(ai_provider, search).generate_reply((CONVERSATION[0], question))

    assert reply.content == "answer"
    assert search.queries == [("Any NEWS on 2330?", 2)]
    [sent] = ai_provider.conversations
    assert [message.role for message in sent] == [MessageRole.SYSTEM, MessageRole.SYSTEM, MessageRole.USER]
    assert sent[1].content == ("Context:\nRecent web search results:\n\n[1] TSMC up\nURL: https://news/1\nContent: Revenue beat.\n")
    assert sent[2] == question


@pytest.mark.parametrize(
    ("question", "results"),
    [
        ("How is 2330?", [WebSearchResult(title="unused", url="https://news/2", content="unused")]),
        ("Any news on 2330?", []),
        ("Any news on 2330?", RuntimeError("search is down")),
    ],
)
async def test_without_a_trigger_word_or_usable_results_the_conversation_goes_as_it_is(
    question: str, results: list[WebSearchResult] | Exception
) -> None:
    ai_provider = FakeAiProvider()
    conversation = (Message(role=MessageRole.USER, content=question, timestamp=NOW),)

    await web_search_adapter(ai_provider, FakeWebSearch(results)).generate_reply(conversation)

    assert ai_provider.conversations == [conversation]


async def test_tavily_sends_the_configured_search_and_reads_at_most_limit_results(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        results = [{"title": " TSMC ", "url": "https://news/1", "snippet": "beat"}, {"title": "second"}, {"title": "third"}]
        return httpx.Response(200, json={"results": results})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(tavily_provider.httpx, "AsyncClient", lambda **options: real_client(transport=httpx.MockTransport(answer)))
    shipped = shipped_config()
    behavior = shipped.behavior.model_copy(update={"web_search_allowed_domains": {"cnyes.com"}})
    config = shipped.model_copy(
        update={"tavily": TavilyConfig(TAVILY_API_KEY="tavily-key", search_depth="advanced"), "behavior": behavior}
    )

    results = await TavilySearchAdapter(config=config, logger=SilentLogger()).search("2330 news", limit=2)

    assert results == [
        WebSearchResult(title="TSMC", url="https://news/1", content="beat"),
        WebSearchResult(title="second", url="", content=""),
    ]
    assert sent == [
        {
            "api_key": "tavily-key",
            "query": "2330 news",
            "max_results": 2,
            "search_depth": "advanced",
            "include_answer": False,
            "include_raw_content": False,
            "include_domains": ["cnyes.com"],
        }
    ]
