from typing import Protocol

from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account_snapshot import AccountSnapshot
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.types.ids import RunId


class ITradingJournal(Protocol):
    """
    The record of what the trading workflows did: runs, decisions, orders and account snapshots.

    The application is the only writer, whichever execution provider ran the orders. Every write is
    an upsert by primary key, so writing the same row again (a run at start and at finish, an order
    before and after the broker call) keeps one row. Rows reference each other: a signal and an
    order name their run, an order names its decision, a snapshot names the order whose fill took it.
    """

    async def save_run(self, run: SystemStats) -> None: ...

    async def save_signals(self, run_id: RunId, signals: list[TradeSignal]) -> None: ...

    async def save_order(self, order: Order) -> None: ...

    async def save_snapshot(self, snapshot: AccountSnapshot) -> None: ...

    async def snapshots(self) -> list[AccountSnapshot]:
        """Every account snapshot, oldest first."""
        ...
