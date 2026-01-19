from typing import Protocol

from src.a_domain.model.chat.message import Message


class PlatformPort(Protocol):
    async def send_message(self, user_id: str, message: Message) -> bool: ...
