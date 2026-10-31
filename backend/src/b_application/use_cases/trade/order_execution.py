import asyncio
import contextlib

from a_domain.model.trading.order import Order
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from b_application.schemas.pipeline_status import PipelineStatus


class OrderExecution:
    """
    Use Case: Send one recorded PENDING order to the broker and record the broker's answer. OrderPreparation recorded
    the order first, so a broker is never called for an order the journal does not hold.

    A cancel (Ctrl-C) during the broker call lets the broker answer and records that answer before it stops the run,
    so the journal never says PENDING about an order the broker saw. A second cancel stops the broker call itself,
    and the order is recorded FAILED with a reason that says to check the broker.
    """

    def __init__(
        self, execution_provider: IExecutionProvider, journal: ITradingJournal, market_clock: IMarketClock, logger: ILoggingProvider
    ) -> None:
        self._execution_provider = execution_provider
        self._journal = journal
        self._market_clock = market_clock
        self._logger = logger

    async def execute(self, order: Order, status: PipelineStatus) -> Order:
        sending = asyncio.ensure_future(self._execution_provider.place_order(order))
        run_cancelled = False

        try:
            await asyncio.wait([sending])
        except asyncio.CancelledError:
            run_cancelled = True
            with contextlib.suppress(BaseException):
                await sending

        now = self._market_clock.now()

        if sending.cancelled():
            order.fail_if_open("the run was cancelled during the broker call, so the broker may hold this order: check it", now=now)
        elif (error := sending.exception()) is not None:
            order.fail_if_open(f"broker call failed: {type(error).__name__}: {error}", now=now)
        else:
            order = sending.result()

        try:
            await self._journal.save_order(order)
        except Exception as error:
            message = f"Order {order.id} ended {order.status} but its record still says PENDING: {error}"
            self._logger.error(status.stats.add_error(message))

        if run_cancelled or sending.cancelled():
            raise asyncio.CancelledError

        return order
