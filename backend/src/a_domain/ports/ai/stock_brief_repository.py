from datetime import date, datetime
from typing import Protocol

from a_domain.model.analysis.stock_brief import StockBrief


class IStockBriefRepository(Protocol):
    """
    The site's AI briefs: one per stock and Taipei calendar day, shared by every viewer and kept across restarts, so a
    day's brief of a stock is paid for once. Past days' briefs are kept.
    """

    async def find(self, stock_id: str, day: date) -> StockBrief | None:
        """The stock's brief of that day, whatever its status."""
        ...

    async def latest_written(self, stock_id: str, before: date) -> StockBrief | None:
        """The stock's newest written brief of a day before `before`."""
        ...

    async def claimed_stocks(self, day: date) -> int:
        """How many stocks have a brief of that day, whatever its status."""
        ...

    async def claim(self, brief: StockBrief, daily_stocks: int, stale_before: datetime) -> bool:
        """
        Takes the day's brief of the stock for one writer, as `brief` states it, and says whether this call took it: it
        does when the stock has no brief of the day while fewer than `daily_stocks` stocks have one, or when its brief of
        the day failed or was claimed before `stale_before` and never written. Of calls made together, one takes it.
        """
        ...

    async def save(self, brief: StockBrief) -> None:
        """Replaces the stock's brief of the day with `brief`."""
        ...

    async def release(self, stock_id: str, day: date) -> None:
        """Removes the stock's brief of the day, so a claim that asked no AI takes none of the day's stocks."""
        ...
