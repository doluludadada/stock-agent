from datetime import datetime
from typing import Protocol

from src.a_domain.model.market.ohlcv import Ohlcv
from src.a_domain.model.market.stock import Stock


class IMarketDataPort(Protocol):
    """
    Interface specifically for Quantitative Data (Left Brain).
    """

    async def get_all_stocks(self) -> list[Stock]: ...

    async def get_price_history(
        self, stock_id: str, start_date: datetime, end_date: datetime
    ) -> list[Ohlcv]: ...
