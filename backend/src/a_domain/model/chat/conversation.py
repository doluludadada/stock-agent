from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import UUID, uuid4

from a_domain.model.chat.message import Message


@dataclass(frozen=True)
class Conversation:
    user_id: str
    created_at: datetime
    updated_at: datetime
    id: UUID = field(default_factory=uuid4)
    selected_model_name: str | None = None
    messages: tuple[Message, ...] = field(default_factory=tuple)

    def clear_history(self, *, now: datetime):
        return replace(self, messages=tuple(), updated_at=now)
