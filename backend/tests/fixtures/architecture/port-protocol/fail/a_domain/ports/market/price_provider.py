from typing import Protocol


class IPriceProvider(Protocol):
    async def fetch(self, stock_id: str) -> float: ...


class StockProvider(Protocol):
    async def list_stocks(self) -> list[str]: ...


class IClock:
    def now(self) -> float:
        return 0.0
