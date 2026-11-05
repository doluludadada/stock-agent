"""The OpenAI-compatible AI adapters, the web search step and Tavily, over fake clients."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace

import anthropic
import httpx
import httpx2
import pytest
from openai import APIConnectionError, AsyncOpenAI
from support.settings import shipped_config

from a_domain.model.chat.message import Message
from a_domain.model.chat.web_search_result import WebSearchResult
from a_domain.types.enums import AiProvider, MessageRole
from b_application.config.ai_config import TavilyConfig
from b_application.config.app_config import AppConfig
from c_infrastructure.ai_models.ai_adapter import claude_adapter, openai_adapter
from c_infrastructure.ai_models.ai_adapter.claude_adapter import ClaudeAdapter
from c_infrastructure.ai_models.ai_adapter.openai_adapter import OpenAIAdapter
from c_infrastructure.ai_models.ai_adapter.web_search_adapter import WebSearchAiAdapter
from c_infrastructure.ai_models.base import BaseAIAdapter
from c_infrastructure.feed import tavily_provider
from c_infrastructure.feed.tavily_provider import TavilySearchAdapter
from d_presentation.dependencies import create_ai_provider

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

    clients: list[dict] = []

    def __init__(self, **client_options) -> None:
        RecordingOpenAI.clients.append(client_options)
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **params) -> Stream:
        RecordingOpenAI.requests.append(params)

        if isinstance(RecordingOpenAI.reply, Exception):
            raise RecordingOpenAI.reply

        return Stream(RecordingOpenAI.reply)


@pytest.fixture
def openai_client(monkeypatch: pytest.MonkeyPatch) -> type[RecordingOpenAI]:
    RecordingOpenAI.requests = []
    RecordingOpenAI.clients = []
    RecordingOpenAI.reply = ["Supply ", "is tight."]
    monkeypatch.setattr(openai_adapter, "AsyncOpenAI", RecordingOpenAI)
    return RecordingOpenAI


def config() -> AppConfig:
    shipped = shipped_config()
    keys = {"openai_api_key": "openai-key", "groq_api_key": "groq-key", "nvidia_api_key": "nvidia-key", "temperature": 0.3}
    return shipped.model_copy(update={"ai": shipped.ai.model_copy(update=keys)})


def openai(settings: AppConfig) -> OpenAIAdapter:
    return OpenAIAdapter(settings, SilentLogger(), "test-model", AiProvider.OPENAI, settings.ai.openai_api_key)


def nvidia(settings: AppConfig) -> OpenAIAdapter:
    return OpenAIAdapter(
        settings, SilentLogger(), "test-model", AiProvider.NVIDIA, settings.ai.nvidia_api_key, settings.sources.ai.nvidia_base_url
    )


def groq(settings: AppConfig) -> OpenAIAdapter:
    return OpenAIAdapter(
        settings, SilentLogger(), "test-model", AiProvider.GROQ, settings.ai.groq_api_key, settings.sources.ai.groq_base_url
    )


@pytest.mark.parametrize("build", [openai, nvidia, groq])
async def test_an_openai_compatible_adapter_sends_every_role_and_joins_the_streamed_reply(
    build: Callable[[AppConfig], BaseAIAdapter], openai_client: type[RecordingOpenAI]
) -> None:
    adapter = build(config())

    reply = await adapter.generate_reply(CONVERSATION)

    assert (reply.role, reply.content) == (MessageRole.ASSISTANT, "Supply is tight.")
    [request] = openai_client.requests
    assert request["messages"] == [{"role": message.role.value, "content": message.content} for message in CONVERSATION]
    assert (request["model"], request["temperature"], request["stream"]) == ("test-model", 0.3, True)


@pytest.mark.parametrize(
    ("build", "apology"),
    [
        (openai, "I'm sorry, I'm having trouble connecting to OpenAI right now. Please try again in a moment."),
        (nvidia, "I'm sorry, I'm having trouble connecting to NVIDIA right now. Please try again in a moment."),
        (groq, "I'm sorry, I'm having trouble connecting to Groq right now. Please try again in a moment."),
    ],
)
async def test_an_openai_compatible_adapter_answers_a_connection_failure_with_an_apology(
    build: Callable[[AppConfig], BaseAIAdapter], apology: str, openai_client: type[RecordingOpenAI]
) -> None:
    openai_client.reply = APIConnectionError(request=httpx.Request("POST", "https://api.example/v1/chat/completions"))
    adapter = build(config())

    reply = await adapter.generate_reply(CONVERSATION)

    assert reply.content == apology


def stream_event(content: str, *, choices: bool = True) -> bytes:
    delta = [{"index": 0, "delta": {"content": content}, "finish_reason": None}] if choices else []
    event = {"id": "x", "object": "chat.completion.chunk", "created": 0, "model": "m", "choices": delta}
    return f"data: {json.dumps(event)}\n\n".encode()


class StreamBody(httpx.AsyncByteStream):
    """A server-sent event stream that raises an exception part where it comes, as a connection that drops does."""

    def __init__(self, parts: list[bytes | Exception]) -> None:
        self._parts = parts

    async def __aiter__(self):
        for part in self._parts:
            if isinstance(part, Exception):
                raise part
            yield part


@pytest.fixture
def served_stream(monkeypatch: pytest.MonkeyPatch) -> list[bytes | Exception]:
    """The real AsyncOpenAI client, answering every request with the parts the test puts in the returned list."""
    parts: list[bytes | Exception] = []

    def client(**options) -> AsyncOpenAI:
        answer = httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=StreamBody(parts))
        transport = httpx.MockTransport(lambda request: answer)
        return AsyncOpenAI(**options, max_retries=0, http_client=httpx.AsyncClient(transport=transport))

    monkeypatch.setattr(openai_adapter, "AsyncOpenAI", client)
    return parts


async def test_a_connection_that_drops_during_the_stream_is_answered_with_an_apology(served_stream: list) -> None:
    served_stream += [
        stream_event("Supply "),
        httpx.RemoteProtocolError("peer closed connection without sending complete message body"),
    ]

    reply = await groq(config()).generate_reply(CONVERSATION)

    assert reply.content == "I'm sorry, I'm having trouble connecting to Groq right now. Please try again in a moment."


async def test_a_reply_the_adapter_cannot_read_raises_for_the_caller_to_record(served_stream: list) -> None:
    served_stream += [stream_event("Supply "), stream_event("", choices=False), b"data: [DONE]\n\n"]

    with pytest.raises(IndexError):
        await groq(config()).generate_reply(CONVERSATION)


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


@pytest.mark.parametrize(
    ("provider", "key", "base_url", "model"),
    [
        (AiProvider.NVIDIA, "nvidia-key", "https://integrate.api.nvidia.com/v1", "deepseek-ai/deepseek-v4.1-flash"),
        (AiProvider.GROQ, "groq-key", "https://api.groq.com/openai/v1", "openai/gpt-oss-20b"),
    ],
)
async def test_a_hosted_provider_uses_its_own_key_and_endpoint_and_the_configured_model(
    provider: AiProvider, key: str, base_url: str, model: str, openai_client: type[RecordingOpenAI]
) -> None:
    settings = config().model_copy(update={"ai": config().ai.model_copy(update={"active_model": provider})})

    await create_ai_provider(settings, SilentLogger()).generate_reply(CONVERSATION)

    [client] = openai_client.clients
    [request] = openai_client.requests
    assert (client["api_key"], client["base_url"]) == (key, base_url)
    assert request["model"] == model


async def test_groq_with_web_search_on_puts_the_search_results_into_its_request(
    monkeypatch: pytest.MonkeyPatch, openai_client: type[RecordingOpenAI]
) -> None:
    results = {"results": [{"title": "TSMC up", "url": "https://news/1", "snippet": "Revenue beat."}]}
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        tavily_provider.httpx,
        "AsyncClient",
        lambda **options: real_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=results))),
    )
    shipped = config()
    settings = shipped.model_copy(
        update={
            "ai": shipped.ai.model_copy(
                update={"active_model": AiProvider.GROQ, "rag_injection_prompt": "Context:\n{search_results}"}
            ),
            "behavior": shipped.behavior.model_copy(update={"enable_web_search": True}),
            "tavily": TavilyConfig(TAVILY_API_KEY="tavily-key"),
        }
    )
    question = Message(role=MessageRole.USER, content="Any news on 2330?", timestamp=NOW)

    await create_ai_provider(settings, SilentLogger()).generate_reply((question,))

    [client] = openai_client.clients
    [request] = openai_client.requests
    assert client["base_url"] == "https://api.groq.com/openai/v1"
    assert [message["role"] for message in request["messages"]] == ["system", "user"]
    assert request["messages"][0]["content"].startswith("Context:\nRecent web search results:\n\n[1] TSMC up")


class RecordingAnthropic:
    """Stands in for anthropic.AsyncAnthropic: records each streamed request and returns the scripted final message."""

    requests: list[dict] = []
    reply: SimpleNamespace | Exception

    def __init__(self, **client_options) -> None:
        self.messages = self

    def stream(self, **params) -> RecordingAnthropic:
        RecordingAnthropic.requests.append(params)
        return self

    async def __aenter__(self) -> RecordingAnthropic:
        if isinstance(RecordingAnthropic.reply, Exception):
            raise RecordingAnthropic.reply
        return self

    async def __aexit__(self, *exception) -> None:
        return None

    async def get_final_message(self) -> SimpleNamespace:
        return RecordingAnthropic.reply


def claude_reply(stop_reason: str, *texts: str) -> SimpleNamespace:
    thinking = SimpleNamespace(type="thinking", thinking="")
    blocks = [thinking, *(SimpleNamespace(type="text", text=text) for text in texts)]
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, _request_id="req_test")


@pytest.fixture
def anthropic_client(monkeypatch: pytest.MonkeyPatch) -> type[RecordingAnthropic]:
    RecordingAnthropic.requests = []
    monkeypatch.setattr(claude_adapter, "AsyncAnthropic", RecordingAnthropic)
    return RecordingAnthropic


def claude(settings: AppConfig) -> ClaudeAdapter:
    keyed = settings.model_copy(update={"ai": settings.ai.model_copy(update={"anthropic_api_key": "claude-key"})})
    return ClaudeAdapter(config=keyed, logger=SilentLogger(), model_name="claude-haiku-5-5")


async def test_claude_gets_the_system_prompt_apart_and_no_temperature(anthropic_client: type[RecordingAnthropic]) -> None:
    anthropic_client.reply = claude_reply("end_turn", "Supply ", "is tight.")

    reply = await claude(config()).generate_reply(CONVERSATION)

    [request] = anthropic_client.requests
    assert (reply.role, reply.content) == (MessageRole.ASSISTANT, "Supply is tight.")
    assert request["system"] == "You are an analyst."
    assert request["messages"] == [{"role": message.role.value, "content": message.content} for message in CONVERSATION[1:]]
    assert (request["model"], request["max_tokens"], "temperature" in request) == ("claude-haiku-5-5", 16000, False)


@pytest.mark.parametrize(
    ("reply", "apology"),
    [
        (
            anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")),
            "I'm sorry, I'm having trouble connecting to Claude right now. Please try again in a moment.",
        ),
        (claude_reply("refusal"), "I'm sorry, Claude declined to answer this request."),
    ],
)
async def test_claude_answers_a_failure_or_a_refusal_with_an_apology(
    reply: object, apology: str, anthropic_client: type[RecordingAnthropic]
) -> None:
    anthropic_client.reply = reply

    assert (await claude(config()).generate_reply(CONVERSATION)).content == apology


async def test_claude_refuses_to_start_without_its_key() -> None:
    settings = config()
    without_key = settings.model_copy(update={"ai": settings.ai.model_copy(update={"anthropic_api_key": None})})

    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        ClaudeAdapter(config=without_key, logger=SilentLogger(), model_name="claude-haiku-5-5")
