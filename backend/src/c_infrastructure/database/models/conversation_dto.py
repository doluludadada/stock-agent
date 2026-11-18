from datetime import datetime
from typing import Any, ClassVar, Self
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from a_domain.model.chat.conversation import Conversation
from a_domain.model.chat.message import Message
from c_infrastructure.database.utc_datetime import UtcDateTime

MESSAGES = TypeAdapter(tuple[Message, ...])
"""How the messages column holds a conversation's messages: a JSON list in their order, each with its id, role, text and time."""


class ConversationDTO(SQLModel, table=True):
    """
    One chat user's conversation (Conversation), one row per user id of the chat platform (LINE), which names no user
    of the site, so the table has no owner.
    """

    __tablename__: ClassVar[str] = "chat_conversations"

    user_id: str = Field(primary_key=True)
    conversation_id: UUID
    selected_model_name: str | None = None
    created_at: datetime = Field(sa_type=UtcDateTime)
    updated_at: datetime = Field(sa_type=UtcDateTime)
    messages: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))

    @classmethod
    def from_domain(cls, conversation: Conversation) -> Self:
        return cls(
            user_id=conversation.user_id,
            conversation_id=conversation.id,
            selected_model_name=conversation.selected_model_name,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            messages=MESSAGES.dump_python(conversation.messages, mode="json"),
        )

    def to_domain(self) -> Conversation:
        return Conversation(
            user_id=self.user_id,
            id=self.conversation_id,
            selected_model_name=self.selected_model_name,
            created_at=self.created_at,
            updated_at=self.updated_at,
            messages=MESSAGES.validate_python(self.messages),
        )
