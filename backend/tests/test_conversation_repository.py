from datetime import UTC, datetime
from pathlib import Path

import chromadb
import pytest

from a_domain.model.chat.conversation import Conversation
from a_domain.model.chat.message import Message
from a_domain.types.enums import MessageRole
from c_infrastructure.database.chroma.conversation_repository import ChromaConversationRepository
from c_infrastructure.database.chroma.knowledge_repository import ChromaKnowledgeRepository
from c_infrastructure.database.models.user_dto import LEGACY_OWNER_ID
from d_presentation.dependencies import knowledge_collection

pytestmark = pytest.mark.asyncio

STARTED = datetime(2026, 10, 30, 1, 0, tzinfo=UTC)
ANSWERED = datetime(2026, 10, 30, 1, 5, tzinfo=UTC)


class SilentLogger:
    def __getattr__(self, name: str):
        return lambda message: None


def conversation(user_id: str) -> Conversation:
    messages = (
        Message(role=MessageRole.SYSTEM, content="You are an analyst.", timestamp=STARTED),
        Message(role=MessageRole.USER, content="台積電今天如何？", timestamp=ANSWERED),
        Message(role=MessageRole.ASSISTANT, content="It closed higher.", timestamp=ANSWERED),
    )
    return Conversation(user_id=user_id, messages=messages, created_at=STARTED, updated_at=ANSWERED)


async def test_a_saved_conversation_reads_back_whole(tmp_path: Path) -> None:
    repository = ChromaConversationRepository(chromadb.PersistentClient(path=str(tmp_path)), SilentLogger())
    saved = conversation("U1")

    assert await repository.save(saved) is True

    assert await repository.get_conversation_by_user_id("U1") == saved
    assert await repository.get_conversation_by_user_id("U2") is None


async def test_conversations_and_decisions_share_one_store_without_mixing(tmp_path: Path) -> None:
    client = chromadb.PersistentClient(path=str(tmp_path))
    conversations = ChromaConversationRepository(client, SilentLogger())
    knowledge = ChromaKnowledgeRepository(client, knowledge_collection(LEGACY_OWNER_ID), SilentLogger())

    saved = conversation("2330")

    await conversations.save(saved)

    assert await knowledge.find_decision_history("2330") == ""
    assert await conversations.get_conversation_by_user_id("2330") == saved
