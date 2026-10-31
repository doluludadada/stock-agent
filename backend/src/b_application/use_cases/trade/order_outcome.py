from a_domain.model.trading.account_snapshot import AccountSnapshot
from a_domain.model.trading.order import Order
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.enums import OrderStatus
from b_application.schemas.pipeline_status import PipelineStatus


class OrderOutcome:
    """
    Use Case: Take the broker's answer to one sent order into the run. After a fill it re-reads the account and saves
    its snapshot; then the order joins the run's orders, a broker refusal counts as refused, and a failure is a run error.
    """

    def __init__(
        self, execution_provider: IExecutionProvider, journal: ITradingJournal, market_clock: IMarketClock, logger: ILoggingProvider
    ) -> None:
        self._execution_provider = execution_provider
        self._journal = journal
        self._market_clock = market_clock
        self._logger = logger

    async def execute(self, order: Order, status: PipelineStatus) -> None:
        try:
            if order.filled_quantity > 0:
                status.account = await self._execution_provider.get_account()
                snapshot = AccountSnapshot.after_fill(order, status.account, status.stocks_cache.values(), self._market_clock.now())
                await self._journal.save_snapshot(snapshot)
        except Exception as error:
            self._logger.error(status.stats.add_error(f"Account snapshot after {order.stock_id} fill not saved: {error}"))

        status.orders.append(order)

        if order.status == OrderStatus.REJECTED:
            status.stats.orders_refused += 1

        if order.status == OrderStatus.FAILED:
            self._logger.error(status.stats.add_error(f"Order failed: {order.stock_id}, reason={order.reason}"))
            return

        self._logger.info(f"Order {order.summary}")
