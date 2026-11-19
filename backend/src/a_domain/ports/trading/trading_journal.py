from datetime import datetime
from typing import Protocol

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import AccountSnapshot
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.types.enums import ExecutionProvider, Workflow
from a_domain.types.ids import RunId


class ITradingJournal(Protocol):
    """
    The record of what the trading workflows did: runs, decisions, orders and account snapshots. An order and a
    snapshot belong to the broker their run chose (SystemStats.execution_provider), so each broker's account reads
    only its own.

    The application is the only writer, whichever execution provider ran the orders. Every write is
    an upsert by primary key, so writing the same row again (a run at start and at finish, an order
    before and after the broker call) keeps one row. Rows reference each other: a signal and an
    order name their run, an order names its decision, a snapshot names the order whose fill took it.
    """

    async def save_run(self, run: SystemStats) -> None: ...

    async def save_signals(self, run_id: RunId, signals: list[TradeSignal]) -> None: ...

    async def save_order(self, order: Order) -> None: ...

    async def save_snapshot(self, snapshot: AccountSnapshot) -> None: ...

    async def snapshots(self, broker: ExecutionProvider, since: datetime | None = None) -> list[AccountSnapshot]:
        """Every snapshot of the account at `broker`, taken at or after `since` (every one for None), oldest first."""
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
        was saved, its price as a one-bar daily history at its time, a daily close the order gates refuse: an order on
        one is priced only by the realtime quote buy_manually fetches for it.
        """
        ...

    async def recent_runs(self, limit: int, offset: int = 0) -> list[SystemStats]:
        """`limit` runs, newest first, after skipping the `offset` newest."""
        ...

    async def find_run(self, run_id: RunId) -> SystemStats | None: ...

    async def signals_of(self, run_id: RunId) -> list[TradeSignal]:
        """The run's decisions, HOLD included, oldest first."""
        ...

    async def decision_history(self, stock_id: str, limit: int = 3) -> list[TradeSignal]:
        """
        The `limit` newest decisions on the stock whose source is in the decision history (SignalSource), HOLD
        included, of any run, newest first: what the AI reads again of its past analysis.
        """
        ...

    async def orders_of(self, run_id: RunId) -> list[Order]:
        """The run's orders, oldest first."""
        ...

    async def follows_of(self, run_id: RunId) -> list[tuple[TradeSignal, Order]]:
        """Every decision, of any run, that follows a decision of this run and got an order, with that order, oldest first."""
        ...

    async def trades(
        self, broker: ExecutionProvider, since: datetime | None, limit: int, offset: int
    ) -> list[tuple[Order, SystemStats]]:
        """
        `limit` orders of runs on `broker` that filled at least one share, created at or after `since`, newest first,
        after the `offset` newest. Each comes with the run whose decision it carried out: a follow's order with the run
        it followed, every other order with its own run.
        """
        ...

    async def runs_of(self, workflow: Workflow, broker: ExecutionProvider, since: datetime | None) -> list[SystemStats]:
        """The runs of `workflow` on `broker` that started at or after `since` (ever for None), oldest first."""
        ...

    async def first_fill(self, workflow: Workflow, broker: ExecutionProvider, since: datetime | None) -> datetime | None:
        """
        When the first order of a run of `workflow` on `broker` that filled at least one share was created, at or after
        `since` (ever for None). None when no such order filled.
        """
        ...

    async def buy_orders(self, broker: ExecutionProvider, since: datetime) -> list[Order]:
        """Every BUY order of the runs on `broker` created at or after `since`, whatever its status, oldest first."""
        ...

    async def unfinished_runs(self, broker: ExecutionProvider, started_before: datetime) -> list[SystemStats]:
        """
        The runs on `broker` without an end that started before `started_before`, oldest first: with the start of the
        process that asks, the runs an earlier process left when it stopped.
        """
        ...

    async def unsettled_orders(self, broker: ExecutionProvider) -> list[Order]:
        """
        The orders that await settlement (OrderStatus.awaits_settlement) of every run on `broker` that ended, oldest
        first: never of a run still under way, whose parts may be in flight.
        """
        ...
