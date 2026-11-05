from typing import Protocol

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import AccountSnapshot
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

    async def save_stock_reports(self, run_id: RunId, stocks: list[Stock]) -> None:
        """
        A specific-stock analysis's analysed stocks, in the order they were asked for, as they stand now: their name,
        latest price and its time, technical and AI reports and composite score. Saving again replaces them.
        """
        ...

    async def stock_reports_of(self, run_id: RunId) -> list[Stock]:
        """
        The stocks saved under the run, in their saved order; none for any other workflow. Each comes back with what
        was saved, its price as a one-bar daily history at its time; never route one into an order.
        """
        ...

    async def recent_runs(self, limit: int, offset: int = 0) -> list[SystemStats]:
        """`limit` runs, newest first, after skipping the `offset` newest."""
        ...

    async def find_run(self, run_id: RunId) -> SystemStats | None: ...

    async def signals_of(self, run_id: RunId) -> list[TradeSignal]:
        """The run's decisions, HOLD included, oldest first."""
        ...

    async def orders_of(self, run_id: RunId) -> list[Order]:
        """The run's orders, oldest first."""
        ...
