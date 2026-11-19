from typing import Protocol

from a_domain.model.market.news import News


class INewsStore(Protocol):
    async def save(self, news: list[News]) -> None: ...
