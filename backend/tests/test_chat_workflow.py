"""The LINE chat workflow, Pipeline.reply_to_chat, on the real runtime with only the ports faked (tests/support)."""

import pytest
from support.harness import build_harness

from a_domain.model.chat.conversation import Conversation
from a_domain.model.chat.message import Message
from a_domain.types.enums import MessageRole

pytestmark = pytest.mark.asyncio


async def test_a_chat_message_gets_the_ai_reply_and_the_conversation_remembers_both() -> None:
    harness = build_harness()
    harness.ai.chat_reply = "**Hello** there\n\nTSMC reports next week"

    await harness.runtime.pipeline.reply_to_chat("U1", "any news on 2330?")

    assert harness.chat_platform.sent == [("U1", "Hello there"), ("U1", "TSMC reports next week")]
    assert [message.content for message in harness.ai.chat_conversations[0]] == ["any news on 2330?"]
    remembered = harness.conversations.conversations["U1"].messages
    assert [(message.role, message.content) for message in remembered] == [
        (MessageRole.USER, "any news on 2330?"),
        (MessageRole.ASSISTANT, "Hello there"),
        (MessageRole.ASSISTANT, "TSMC reports next week"),
    ]


async def test_a_reset_command_clears_the_conversation_without_asking_the_ai() -> None:
    harness = build_harness()
    harness.ai.chat_reply = "never sent"
    now = harness.clock.now()
    earlier = (
        Message(role=MessageRole.USER, content="hi", timestamp=now),
        Message(role=MessageRole.ASSISTANT, content="hello", timestamp=now),
    )
    harness.conversations.conversations["U1"] = Conversation(user_id="U1", messages=earlier, created_at=now, updated_at=now)

    await harness.runtime.pipeline.reply_to_chat("U1", " clear ")

    assert harness.conversations.conversations["U1"].messages == ()
    assert harness.ai.chat_conversations == []
    assert len(harness.chat_platform.sent) == 1 and harness.chat_platform.sent[0][0] == "U1"
