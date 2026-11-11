from typing import Protocol

from a_domain.model.trading.backtest import Backtest
from a_domain.types.ids import BacktestId


class IBacktestRepository(Protocol):
    """
    One owner's saved backtests; dependencies.py builds one per owner, so the owner is the adapter's and never an
    argument. One owner's backtests are never read or deleted by another.
    """

    async def save(self, backtest: Backtest, keep: int) -> None:
        """Saves the backtest, then deletes the owner's oldest ones beyond the newest `keep`, in one transaction."""
        ...

    async def saved(self) -> list[Backtest]:
        """Every backtest the owner has saved, newest first."""
        ...

    async def get(self, backtest_id: BacktestId) -> Backtest | None: ...

    async def delete(self, backtest_id: BacktestId) -> bool:
        """Whether the owner had a backtest of that id, now deleted."""
        ...
