from datetime import datetime
from typing import Protocol

from src.a_domain.model.analysis.signal import TradeSignal


class ISignalRepositoryPort(Protocol):
    """Repository for persisting and retrieving trade signals."""

    async def save(self, signal: TradeSignal) -> None: ...

    async def save_batch(self, signals: list[TradeSignal]) -> None: ...

    async def get_by_stock_id(
        self,
        stock_id: str,
        start_date: datetime | None = None,
        limit: int = 10,
    ) -> list[TradeSignal]: ...

    async def get_latest(self, limit: int = 50) -> list[TradeSignal]: ...
