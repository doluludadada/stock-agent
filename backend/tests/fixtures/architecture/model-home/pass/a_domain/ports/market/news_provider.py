from typing import Protocol

from a_domain.model.market.news import News


class INewsProvider(Protocol):
    async def fetch(self, stock_id: str) -> list[News]: ...
