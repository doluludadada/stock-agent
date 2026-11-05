from collections.abc import Mapping

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account
from a_domain.model.trading.order import Order
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.account_value import FillSnapshotRule
from a_domain.types.enums import OrderStatus


class OrderOutcome:
    """
    Use Case: Take one order's outcome into the run. After a fill it re-reads the account, saves its snapshot and
    returns that account, so the run's later decisions see it; otherwise the account stays as it was. A refused order,
    by the order gates or by the broker, counts as refused.
    """

    def __init__(
        self, execution_provider: IExecutionProvider, journal: ITradingJournal, market_clock: IMarketClock, logger: ILoggingProvider
    ) -> None:
        self._execution_provider = execution_provider
        self._journal = journal
        self._market_clock = market_clock
        self._snapshot_rule = FillSnapshotRule()
        self._logger = logger

    async def execute(self, order: Order, account: Account, stocks: Mapping[str, Stock], stats: SystemStats) -> Account:
        try:
            if order.filled_quantity > 0:
                stats.orders_filled += 1
                account = await self._execution_provider.get_account()
                snapshot = self._snapshot_rule.apply(order, account, stocks.values(), self._market_clock.now())
                await self._journal.save_snapshot(snapshot)
        except Exception as error:
            self._logger.error(stats.add_error(f"Account snapshot after {order.stock_id} fill not saved: {error}"))

        if order.status == OrderStatus.REJECTED:
            stats.orders_refused += 1

        self._logger.info(f"Order {order.summary}")

        return account
