"""The LINE webhook, POST /v1/webhook/line, on the real app over the harness runtime."""

import base64
import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from support.harness import CliHarness, build_harness, open_harness_switch

from b_application.config.chat_config import LineConfig
from d_presentation.web.app import create_app

pytestmark = pytest.mark.asyncio

SECRET = "line-channel-secret"
WEBHOOK = "/v1/webhook/line"


@asynccontextmanager
async def serve(harness: CliHarness, secret: str | None = SECRET) -> AsyncIterator[httpx.AsyncClient]:
    harness.config.line = LineConfig(LINE_CHANNEL_SECRET=secret)
    app = create_app(lambda: open_harness_switch(harness))

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client,
    ):
        yield client


def text_event(user_id: str, text: str) -> dict:
    return {"type": "message", "message": {"type": "text", "id": "1", "text": text}, "source": {"type": "user", "userId": user_id}}


def signature(body: bytes, secret: str = SECRET) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


async def post(client: httpx.AsyncClient, body: bytes, line_signature: str | None) -> httpx.Response:
    headers = {"Content-Type": "application/json"} | ({"X-Line-Signature": line_signature} if line_signature else {})
    return await client.post(WEBHOOK, content=body, headers=headers)


async def test_a_signed_text_message_gets_the_ai_reply() -> None:
    harness = build_harness()
    harness.ai.chat_reply = "TSMC reports next week"
    body = json.dumps({"destination": "bot", "events": [text_event("U1", "any news on 2330?")]}).encode()

    async with serve(harness) as client:
        response = await post(client, body, signature(body))

    assert (response.status_code, response.json()) == (200, {"status": "ok"})
    assert harness.chat_platform.sent == [("U1", "TSMC reports next week")]


@pytest.mark.parametrize("line_signature", [None, signature(b"another body"), signature(b"{}", secret="another secret")])
async def test_a_call_without_lines_signature_over_its_body_is_refused(line_signature: str | None) -> None:
    harness = build_harness()
    harness.ai.chat_reply = "never sent"
    body = json.dumps({"destination": "bot", "events": [text_event("U1", "hello")]}).encode()

    async with serve(harness) as client:
        response = await post(client, body, line_signature)

    assert response.status_code == 403
    assert harness.chat_platform.sent == []
    assert harness.ai.chat_conversations == []


async def test_a_signed_body_that_is_not_a_webhook_payload_is_a_bad_request() -> None:
    harness = build_harness()
    body = b'{"events": "not a list"}'

    async with serve(harness) as client:
        response = await post(client, body, signature(body))

    assert response.status_code == 400
    assert harness.chat_platform.sent == []


async def test_only_text_messages_are_answered() -> None:
    harness = build_harness()
    harness.ai.chat_reply = "hello"
    sticker = {"type": "message", "message": {"type": "sticker", "id": "2"}, "source": {"type": "user", "userId": "U1"}}
    follow = {"type": "follow", "source": {"type": "user", "userId": "U2"}}
    body = json.dumps({"destination": "bot", "events": [sticker, follow, text_event("U3", "hi")]}).encode()

    async with serve(harness) as client:
        response = await post(client, body, signature(body))

    assert response.status_code == 200
    assert harness.chat_platform.sent == [("U3", "hello")]


async def test_without_a_channel_secret_no_call_is_answered() -> None:
    harness = build_harness()
    harness.ai.chat_reply = "never sent"
    body = json.dumps({"destination": "bot", "events": [text_event("U1", "hello")]}).encode()

    async with serve(harness, secret=None) as client:
        response = await post(client, body, signature(body))

    assert response.status_code == 500
    assert harness.chat_platform.sent == []
