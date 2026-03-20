from typing import Protocol

from a_domain.model.chat.message import Message


class IAiProvider(Protocol):
    async def generate_reply(self, messages: tuple[Message, ...]) -> Message: ...

    def save_response(self, stock_id: str, content: str) -> None:
        """Saves the raw AI response for later inspection."""
        ...
