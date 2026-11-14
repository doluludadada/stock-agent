from collections.abc import Sequence
from typing import Protocol


class ITextEmbedder(Protocol):
    """
    Turns texts into vectors of one length each, closer together the more alike the texts mean. It computes on the
    server itself: no text leaves it and no call is paid for. The work is heavy, so `embed` runs it off the event loop,
    one batch at a time for the whole process.
    """

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, in the texts' order. The first text opens the model. Raises when it cannot be opened."""
        ...
