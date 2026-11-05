from collections.abc import Sequence

from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.enums import OrderStatus, TradeAction
from b_application.config.app_config import AppConfig


class OrderPreparation:
    """
    Use Case: Turn one recorded BUY or SELL decision into its order and record that order before anything is sent.

    Every orderable decision gets exactly one order, saved in the journal with its run and decision ids and handed
    back: REJECTED by OrderRule (order mode, market closed, stale price), or PENDING for OrderExecution to send.
    OrderRule reads the clock here, right before the send, so a quote that aged while the run analysed other stocks
    is refused. A decision that already has an order in this run gets none, so a workflow can send stop-loss SELLs
    early and the rest at the end. An order whose record cannot be saved is FAILED, so OrderExecution never sends it.
    """

    def __init__(self, journal: ITradingJournal, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider) -> None:
        self._journal = journal
        self._market_clock = market_clock
        self._order_rule = config.order_rule()
        self._logger = logger

    async def execute(self, signal: TradeSignal, orders: Sequence[Order], stats: SystemStats) -> Order | None:
        if signal.action == TradeAction.HOLD or signal.decision_id in {order.decision_id for order in orders}:
            return None

        order = self._order_rule.apply(signal, stats.run_id, self._market_clock.now(), self._market_clock.trading_phase())

        try:
            await self._journal.save_order(order)
        except Exception as error:
            order.fail_if_open(
                f"the order record could not be saved, so the order was not sent: {error}", now=self._market_clock.now()
            )
            self._logger.error(stats.add_error(f"Order record not saved: {order.stock_id}, error={error}"))
            return order

        if order.status == OrderStatus.PENDING:
            stats.orders_submitted += 1

        return order
