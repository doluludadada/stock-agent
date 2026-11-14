from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.ids import RunId


class RunLookup:
    """
    The recorded runs as the journal keeps them, whichever entry point started them: a page of their records, newest
    first, or with `run_id` that one run's record, its specific-stock reports, its decisions and its orders.
    """

    def __init__(self, journal: ITradingJournal) -> None:
        self._journal = journal

    async def execute(
        self, run_id: RunId | None = None, *, limit: int = 0, offset: int = 0
    ) -> tuple[list[SystemStats], list[Stock], list[TradeSignal], list[Order]]:
        """The records, then the one run's reports, decisions and orders. No record when the journal holds no such run."""
        if run_id is None:
            return await self._journal.recent_runs(limit, offset), [], [], []

        record = await self._journal.find_run(run_id)

        if record is None:
            return [], [], [], []

        reports = await self._journal.stock_reports_of(run_id)
        signals = await self._journal.signals_of(run_id)
        orders = await self._journal.orders_of(run_id)

        return [record], reports, signals, orders
