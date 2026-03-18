from datetime import datetime
from typing import Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock


class IPriceProvider(Protocol):
    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]: ...
    async def fetch_history(self, stock: Stock, start_date: datetime, end_date: datetime) -> list[Ohlcv]: ...
