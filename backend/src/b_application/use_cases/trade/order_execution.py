import asyncio

from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.enums import OrderStatus, TradeAction
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.trade.account_loader import AccountLoader


class OrderExecution:
    """
    Use Case: Turn recorded BUY/SELL decisions into orders.

    Every orderable decision gets exactly one order, saved in the journal with its run and decision ids:
    - REJECTED by OrderRule (order mode, market closed, stale price) and never sent, or
    - saved PENDING first, then sent, then saved again with the broker's result.
    A broker is never called for an order the journal does not hold. A decision that already has an
    order in this run is skipped, so a workflow can send stop-loss SELLs early and the rest at the end.
    After any fill, AccountLoader re-reads the account and snapshots it.

    A cancel (Ctrl-C) during the send waits for the broker's answer and its record before it stops the
    run, so the journal never says PENDING about an order the broker saw.
    """

    def __init__(
        self,
        execution_provider: IExecutionProvider,
        journal: ITradingJournal,
        account_loader: AccountLoader,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._execution_provider = execution_provider
        self._journal = journal
        self._account_loader = account_loader
        self._market_clock = market_clock
        self._order_rule = config.order_rule()
        self._logger = logger

    async def execute(self, signals: list[TradeSignal], status: PipelineStatus) -> None:
        handled_decisions = {order.decision_id for order in status.orders}

        for signal in signals:
            if signal.action == TradeAction.HOLD or signal.decision_id in handled_decisions:
                continue

            handled_decisions.add(signal.decision_id)
            order = self._order_rule.order_for(
                signal, status.stats.run_id, now=self._market_clock.now(), phase=self._market_clock.trading_phase()
            )

            try:
                await self._journal.save_order(order)

            except Exception as error:
                if order.status == OrderStatus.PENDING:
                    order.fail(f"the order record could not be saved, so the order was not sent: {error}")

                status.orders.append(order)
                self.record_error(status, f"Order record not saved: {order.stock_id}, error={error}")
                continue

            if order.status == OrderStatus.PENDING:
                status.stats.orders_submitted += 1
                sending = asyncio.ensure_future(self.send(order, status))

                try:
                    order = await asyncio.shield(sending)

                except asyncio.CancelledError:
                    await sending
                    raise

            status.orders.append(order)

            if order.status == OrderStatus.REJECTED:
                status.stats.orders_refused += 1

            if order.status == OrderStatus.FAILED:
                self.record_error(status, f"Order failed: {order.stock_id}, reason={order.reason}")
                continue

            self._logger.info(
                f"Order {order.status.value.upper()}: {order.action.value.upper()} {order.stock_id} "
                f"filled {order.filled_quantity}/{order.quantity} @ {order.limit_price}, fee={order.fee}, tax={order.tax}"
                + (f", reason={order.reason}" if order.reason else "")
            )

    async def send(self, order: Order, status: PipelineStatus) -> Order:
        """Sends a recorded PENDING order and records the broker's answer. Cancelled itself, it records the order FAILED."""
        try:
            order = await self._execution_provider.place_order(order)

        except asyncio.CancelledError:
            if order.status in {OrderStatus.PENDING, OrderStatus.SUBMITTED}:
                order.fail("the run was cancelled during the broker call, so the broker may hold this order: check it")

            await self.record(order, status)
            raise

        except Exception as error:
            if order.status in {OrderStatus.PENDING, OrderStatus.SUBMITTED}:
                order.fail(f"broker call failed: {type(error).__name__}: {error}")

        await self.record(order, status)

        if order.filled_quantity > 0:
            try:
                await self._account_loader.record_fill(status, order)

            except Exception as error:
                self.record_error(status, f"Account snapshot after {order.stock_id} fill not saved: {error}")

        return order

    async def record(self, order: Order, status: PipelineStatus) -> None:
        try:
            await self._journal.save_order(order)

        except Exception as error:
            self.record_error(status, f"Order {order.id} ended {order.status} but its record still says PENDING: {error}")

    def record_error(self, status: PipelineStatus, message: str) -> None:
        self._logger.error(message)
        status.stats.add_error(message)
