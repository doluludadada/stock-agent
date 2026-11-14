from collections.abc import Sequence

from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.ordering_switch import IOrderingSwitch
from a_domain.ports.system.user_store import IUserStore
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.enums import OrderStatus, TradeAction
from a_domain.types.ids import UserId
from b_application.config.app_config import AppConfig


class OrderPreparation:
    """
    Use Case: Turn one recorded BUY or SELL decision into its order and record that order before anything is sent.

    Every orderable decision gets exactly one order, saved in the journal with its run and decision ids and handed
    back: REJECTED by OrderRule (market closed, stale price) or by BrokerAccessRule, or PENDING for OrderExecution to
    send to `execution_provider`, the same broker object this one asks. Both read the clock and the broker here, right
    before the send: a quote that aged while the run analysed other stocks is refused, and so is an order the broker
    may not take now. BrokerAccessRule reads what the broker reports of itself (its link) against the run's choice, and
    for a real broker the site's ordering switch as it is now (`ordering_switch`: the settings that serve new work, not
    those this run started on, so turning ordering off stops a run already under way), the user as saved now (`user_id`,
    the Pipeline's user) and the day's BUYs on it in the journal.
    The order is saved PENDING before those BUYs are read, so every order that may reach the broker, this one and one
    of another process of the same owner at the same moment included, is in the total. A decision that already has an
    order in this run gets none, so a workflow can send stop-loss SELLs early and the rest at the end. An order whose
    record cannot be saved is FAILED, so OrderExecution never sends it.
    """

    def __init__(
        self,
        journal: ITradingJournal,
        execution_provider: IExecutionProvider,
        user_store: IUserStore,
        ordering_switch: IOrderingSwitch,
        user_id: UserId | None,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._journal = journal
        self._execution_provider = execution_provider
        self._user_store = user_store
        self._ordering_switch = ordering_switch
        self._user_id = user_id
        self._market_clock = market_clock
        self._order_rule = config.order_rule()
        self._access_rule = config.broker_access_rule()
        self._logger = logger

    async def execute(self, signal: TradeSignal, orders: Sequence[Order], stats: SystemStats) -> Order | None:
        if signal.action == TradeAction.HOLD or signal.decision_id in {order.decision_id for order in orders}:
            return None

        link, now = self._execution_provider.link(), self._market_clock.now()
        day_start = self._market_clock.to_market_datetime(now).replace(hour=0, minute=0, second=0, microsecond=0)
        user = await self._user_store.find(self._user_id) if link.broker.real and self._user_id is not None else None
        last_close = self._market_clock.session_close(self._market_clock.last_closed_session())
        order = self._order_rule.apply(signal, stats.run_id, now, self._market_clock.trading_phase(), last_close)

        try:
            await self._journal.save_order(order)
            buys = await self._journal.buy_orders(link.broker, day_start) if link.broker.real and order.status.is_open else []
            ordering = self._ordering_switch.visibility(link.broker)
            refusal = self._access_rule.apply(order, stats.execution_provider, link, user, ordering, buys)

            if order.status.is_open and refusal is not None:
                order.reject(*refusal, now=now)
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
