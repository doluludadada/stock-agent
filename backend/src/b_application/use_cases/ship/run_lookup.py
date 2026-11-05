from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.ids import RunId


class RunLookup:
    """One recorded run as the journal keeps it: its record, its specific-stock reports, its decisions and its orders."""

    def __init__(self, journal: ITradingJournal) -> None:
        self._journal = journal

    async def execute(self, run_id: RunId) -> tuple[SystemStats, list[Stock], list[TradeSignal], list[Order]] | None:
        """None when the journal holds no such run."""
        record = await self._journal.find_run(run_id)

        if record is None:
            return None

        reports = await self._journal.stock_reports_of(run_id)
        signals = await self._journal.signals_of(run_id)
        orders = await self._journal.orders_of(run_id)

        return record, reports, signals, orders
