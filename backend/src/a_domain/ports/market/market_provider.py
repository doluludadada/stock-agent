from datetime import datetime
from typing import Protocol

from backend.src.a_domain.model.market.ohlcv import Ohlcv


class IMarketProvider(Protocol):
    async def fetch_realtime_bars(self, stock_ids: list[str]) -> dict[str, Ohlcv]: ...
    async def fetch_history(self, stock_id: str, start_date: datetime, end_date: datetime) -> list[Ohlcv]: ...
