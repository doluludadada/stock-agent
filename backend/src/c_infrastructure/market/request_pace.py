import asyncio
import time
from dataclasses import dataclass, field


@dataclass(eq=False)
class RequestPace:
    """
    When the latest request to one host left, kept by whoever shares that host's limit. A request waits its turn, then
    until the interval has passed since the request before it, so requests made at once leave one interval apart.
    """

    last_request_at: float | None = None
    turn: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def wait(self, interval_seconds: float) -> None:
        async with self.turn:
            if self.last_request_at is not None:
                await asyncio.sleep(max(0.0, interval_seconds - (time.monotonic() - self.last_request_at)))

            self.last_request_at = time.monotonic()
