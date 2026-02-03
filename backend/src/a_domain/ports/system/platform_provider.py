from typing import Protocol

from backend.src.a_domain.model.chat.message import Message


class IPlatformProvider(Protocol):
    async def send_message(self, user_id: str, message: Message) -> bool: ...


