from datetime import datetime
from typing import Protocol


class IMarketClock(Protocol):
    def now(self) -> datetime: ...
