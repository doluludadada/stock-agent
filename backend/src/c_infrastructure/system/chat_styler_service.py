import re
from typing import override

from a_domain.model.chat.message import Message, MessageRole
from a_domain.ports.chat.chat_styler_provider import IChatStylerProvider


class ChatStylerService(IChatStylerProvider):
    def __init__(self, sentence_endings: str, max_message_length: int) -> None:
        self._sentence_endings = sentence_endings
        self._max_message_length = max_message_length

    @override
    def format_response(self, message: Message) -> tuple[Message, ...]:
        """
        Plain-text chat messages from an AI reply: markdown emphasis, headings and code blocks are removed, each paragraph
        is its own message, and a paragraph longer than the limit is cut after its last sentence ending, else at its last
        space, else at the limit. Every cut moves forward, so any paragraph ends.
        """
        text = re.sub(r"\*\*(.*?)\*\*|\*(.*?)\*", r"\1\2", message.content)
        text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL).strip()
        parts: list[str] = []

        for paragraph in re.split(r"\n\n+", text):
            remaining = paragraph.strip()

            while len(remaining) > self._max_message_length:
                split_at = max(remaining.rfind(ending, 0, self._max_message_length) for ending in self._sentence_endings) + 1

                if split_at == 0:
                    split_at = remaining.rfind(" ", 0, self._max_message_length)

                if split_at == -1:
                    split_at = self._max_message_length

                parts.append(remaining[:split_at].strip())
                remaining = remaining[split_at:].strip()

            if remaining:
                parts.append(remaining)

        if not parts:
            return (Message(role=MessageRole.ASSISTANT, content="Could you ask me again?🤔", timestamp=message.timestamp),)

        return tuple(Message(role=MessageRole.ASSISTANT, content=part, timestamp=message.timestamp) for part in parts)
