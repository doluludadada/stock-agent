from typing import Protocol


class INewsProvider(Protocol):
    async def fetch_news(self, stock_id: str) -> list[str]: ...
