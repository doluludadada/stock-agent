import asyncio
import time
from collections.abc import Awaitable, Callable
from copy import deepcopy

from a_domain.model.valuation.scan import MarketValuation


class MarketValuationCache:
    """
    The market valuation the Web API last loaded, reused for `ttl_seconds`, so changing a target P/E does not reload
    the listings and MOPS. One load runs at a time: a request that arrives during a load waits for it instead of
    starting its own. Each caller gets its own copy, because the technical step writes history and reports onto the
    stocks it screens.
    """

    def __init__(self, load: Callable[[], Awaitable[MarketValuation]], ttl_seconds: float) -> None:
        self._load = load
        self._ttl_seconds = ttl_seconds
        self._lock = asyncio.Lock()
        self._loaded: tuple[float, MarketValuation] | None = None

    async def get(self) -> MarketValuation:
        async with self._lock:
            if self._loaded is None or time.monotonic() - self._loaded[0] > self._ttl_seconds:
                self._loaded = time.monotonic(), await self._load()

            return deepcopy(self._loaded[1])
