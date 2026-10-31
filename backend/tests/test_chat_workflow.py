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


async def test_a_reply_with_no_text_left_after_formatting_asks_the_user_again() -> None:
    harness = build_harness()
    harness.ai.chat_reply = "```\nprint('only code')\n```"

    await harness.runtime.pipeline.reply_to_chat("U1", "show me code")

    assert harness.chat_platform.sent == [("U1", "Could you ask me again?🤔")]


async def test_a_long_paragraph_is_sent_in_parts_no_longer_than_the_limit() -> None:
    harness = build_harness()
    reply = " ".join(f"word{index}" for index in range(120))
    harness.ai.chat_reply = reply

    await harness.runtime.pipeline.reply_to_chat("U1", "tell me everything")

    parts = [content for _, content in harness.chat_platform.sent]
    assert len(parts) > 1
    assert all(len(part) <= harness.config.sources.line.max_message_length for part in parts)
    assert " ".join(parts) == reply


async def test_a_long_paragraph_is_cut_after_its_last_sentence_ending_and_then_at_the_limit() -> None:
    harness = build_harness()
    limit = harness.config.sources.line.max_message_length
    first_sentence = "A" * (limit - 100) + "。"
    unbroken = "B" * (limit + 50)
    harness.ai.chat_reply = first_sentence + unbroken

    await harness.runtime.pipeline.reply_to_chat("U1", "tell me everything")

    assert [content for _, content in harness.chat_platform.sent] == [first_sentence, "B" * limit, "B" * 50]
