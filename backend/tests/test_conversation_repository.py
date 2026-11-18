from datetime import UTC, datetime, timedelta

import pytest
from support.databases import execute

from a_domain.model.chat.conversation import Conversation
from a_domain.model.chat.message import Message
from a_domain.types.enums import MessageRole
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.conversation_repository import SqlConversationRepository

pytestmark = pytest.mark.asyncio

STARTED = datetime(2026, 10, 30, 1, 0, tzinfo=UTC)
ANSWERED = datetime(2026, 10, 30, 1, 5, tzinfo=UTC)


class SilentLogger:
    def __getattr__(self, name: str):
        return lambda message: None


class RecordingLogger:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)


def conversation(user_id: str) -> Conversation:
    messages = (
        Message(role=MessageRole.SYSTEM, content="You are an analyst.", timestamp=STARTED),
        Message(role=MessageRole.USER, content="台積電今天如何？", timestamp=ANSWERED),
        Message(role=MessageRole.ASSISTANT, content="It closed higher.", timestamp=ANSWERED),
    )
    return Conversation(user_id=user_id, messages=messages, created_at=STARTED, updated_at=ANSWERED)


async def test_a_saved_conversation_reads_back_whole(database: DatabaseConnector) -> None:
    repository = SqlConversationRepository(database, SilentLogger())
    saved = conversation("U1")

    assert await repository.save(saved) is True

    assert await repository.get_conversation_by_user_id("U1") == saved
    assert await repository.get_conversation_by_user_id("U2") is None


async def test_messages_added_later_read_back_after_the_earlier_ones_and_a_cleared_history_reads_back_empty(
    database: DatabaseConnector,
) -> None:
    repository = SqlConversationRepository(database, SilentLogger())
    later = ANSWERED + timedelta(minutes=1)
    await repository.save(conversation("U1"))
    held = await repository.get_conversation_by_user_id("U1")
    assert held is not None

    await repository.save(held.add_messages([Message(role=MessageRole.USER, content="鴻海呢？", timestamp=later)], now=later))
    added = await repository.get_conversation_by_user_id("U1")
    assert added is not None
    await repository.save(added.clear_history(now=later))
    cleared = await repository.get_conversation_by_user_id("U1")

    assert [message.content for message in added.messages] == [
        "You are an analyst.",
        "台積電今天如何？",
        "It closed higher.",
        "鴻海呢？",
    ]
    assert (added.id, added.updated_at) == (held.id, later)
    assert cleared is not None and cleared.messages == () and cleared.id == held.id


async def test_a_save_the_database_cannot_take_is_logged_once_and_answers_false(database: DatabaseConnector) -> None:
    logger = RecordingLogger()
    await execute("DROP TABLE chat_conversations")

    assert await SqlConversationRepository(database, logger).save(conversation("U1")) is False
    assert len(logger.errors) == 1
