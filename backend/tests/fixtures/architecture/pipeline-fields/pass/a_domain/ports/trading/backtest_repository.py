from typing import Protocol


class IBacktestRepository(Protocol):
    async def delete(self, backtest_id: str) -> bool: ...
