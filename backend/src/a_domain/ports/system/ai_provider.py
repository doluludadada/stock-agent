from typing import Protocol

from backend.src.a_domain.model.chat.message import Message


class IAiProvider(Protocol):
    async def generate_reply(self, messages: tuple[Message, ...]) -> Message: ...
