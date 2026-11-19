from typing import Protocol


class IExecutionProvider(Protocol):
    async def place_order(self, stock_id: str, quantity: int) -> None: ...
