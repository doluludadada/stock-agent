from typing import Protocol

from src.a_domain.model.market.stock import Stock


class IWatchlistRepository(Protocol):
    """
    Manages the list of stocks to monitor.
    """

    async def get_daily_candidates(self) -> list[Stock]:
        """Fetch Phase 1 targets (Cold)."""
        ...

    async def save_daily_candidates(self, stocks: list[Stock]) -> None:
        """Save results from Phase 1 Screening."""
        ...
