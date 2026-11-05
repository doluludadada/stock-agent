from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field
from pydantic.dataclasses import dataclass

from a_domain.types.enums import MessageRole


@dataclass(frozen=True, kw_only=True)
class Message:
    id: UUID = Field(default_factory=uuid4)
    role: MessageRole
    content: str
    timestamp: datetime
