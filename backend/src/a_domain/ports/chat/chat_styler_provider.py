from typing import Protocol

from a_domain.model.chat.message import Message


class IChatStylerProvider(Protocol):
    def format_response(self, message: Message) -> tuple[Message, ...]: ...
