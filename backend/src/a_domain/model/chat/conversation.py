from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from a_domain.model.chat.message import Message


@dataclass(frozen=True)
class Conversation:
    user_id: str
    id: UUID = field(default_factory=uuid4)
    selected_model_name: str | None = None
    messages: tuple[Message, ...] = field(default_factory=tuple)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def add_message(self, message: Message):
        new_messages = self.messages + (message,)
        return replace(self, messages=new_messages, updated_at=datetime.now(UTC))

    def add_messages(self, messages: list[Message] | tuple[Message, ...]):
        new_messages = self.messages + tuple(messages)
        return replace(self, messages=new_messages, updated_at=datetime.now(UTC))

    def clear_history(self):
        return replace(self, messages=tuple(), updated_at=datetime.now(UTC))
