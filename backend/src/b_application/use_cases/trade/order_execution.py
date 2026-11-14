import asyncio
import contextlib
from functools import partial

from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.order import Order
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.ordering_switch import IOrderingSwitch
from a_domain.ports.system.user_store import IUserStore
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.order_rule import RealBrokerOrdererRule
from a_domain.types.enums import OrderStatus, RejectReason
from a_domain.types.ids import UserId
from b_application.config.app_config import AppConfig


async def send_refusal(
    execution_provider: IExecutionProvider,
    user_id: UserId | None,
    user_store: IUserStore,
    ordering_switch: IOrderingSwitch,
    orderer_rule: RealBrokerOrdererRule,
) -> tuple[RejectReason, str] | None:
    """
    Why an exchange order may not go to the broker at this moment, or None: for a real broker, the site's ordering
    switch and the user, each as it is now. OrderExecution hands it to the broker, which asks it right before each send.
    """
    broker = execution_provider.link().broker

    if not broker.real:
        return None

    user = await user_store.find(user_id) if user_id is not None else None
    return orderer_rule.apply(broker, user, await ordering_switch.visibility(broker))


class OrderExecution:
    """
    Use Case: Send one recorded PENDING order to the broker and record the broker's answer; any other order comes back
    as it is, unsent. OrderPreparation recorded the order first, so a broker is never called for an order the journal
    does not hold. An order the broker call ends FAILED is a run error.

    The broker asks `refusal_now` right before each exchange order it sends, the second lot part of an order included:
    for a real broker, the site's ordering switch as it is at that moment and the user as saved then
    (RealBrokerOrdererRule), so ordering turned off between the order's preparation and a part's send stops that part.

    A cancel (Ctrl-C) during the broker call lets the broker answer and records that answer before it stops the run,
    so the journal never says PENDING about an order the broker saw. A second cancel stops the broker call itself,
    and the order is recorded FAILED with a reason that says to check the broker.
    """

    def __init__(
        self,
        execution_provider: IExecutionProvider,
        journal: ITradingJournal,
        user_store: IUserStore,
        ordering_switch: IOrderingSwitch,
        user_id: UserId | None,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._execution_provider = execution_provider
        self._journal = journal
        self._market_clock = market_clock
        orderer_rule = config.broker_access_rule().orderer_rule
        self._refusal_now = partial(send_refusal, execution_provider, user_id, user_store, ordering_switch, orderer_rule)
        self._logger = logger

    async def execute(self, order: Order, stats: SystemStats) -> Order:
        if order.status != OrderStatus.PENDING:
            return order

        sending = asyncio.ensure_future(self._execution_provider.place_order(order, self._refusal_now))
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
            self._logger.error(stats.add_error(f"Order {order.id} ended {order.status} but its record still says PENDING: {error}"))
        if run_cancelled or sending.cancelled():
            raise asyncio.CancelledError
        if order.status == OrderStatus.FAILED:
            self._logger.error(stats.add_error(f"Order failed: {order.stock_id}, reason={order.reason}"))
        return order
