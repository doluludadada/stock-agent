from typing import Protocol


class IStockProvider(Protocol):
    async def get_all(self) -> list[str]: ...
