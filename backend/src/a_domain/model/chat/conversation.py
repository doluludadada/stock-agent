from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field
from pydantic.dataclasses import dataclass

from a_domain.model.chat.message import Message


@dataclass(frozen=True)
class Conversation:
    user_id: str
    created_at: datetime
    updated_at: datetime
    id: UUID = Field(default_factory=uuid4)
    selected_model_name: str | None = None
    messages: tuple[Message, ...] = Field(default_factory=tuple)

    def add_messages(self, messages: Iterable[Message], *, now: datetime) -> Conversation:
        """The conversation with these messages added at its end. Without messages it is unchanged."""
        added = tuple(messages)

        if not added:
            return self

        return replace(self, messages=self.messages + added, updated_at=now)

    def clear_history(self, *, now: datetime) -> Conversation:
        return replace(self, messages=tuple(), updated_at=now)
