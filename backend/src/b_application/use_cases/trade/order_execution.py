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
from a_domain.rules.trading.order_rule import RealBrokerGateRule
from a_domain.types.enums import OrderStatus, RejectReason, Workflow
from a_domain.types.ids import UserId
from b_application.config.app_config import AppConfig


async def send_refusal(
    execution_provider: IExecutionProvider,
    user_id: UserId | None,
    user_store: IUserStore,
    ordering_switch: IOrderingSwitch,
    gate_rule: RealBrokerGateRule,
    workflow: Workflow,
    stop: asyncio.Event,
) -> tuple[RejectReason, str] | None:
    """
    Why an exchange order of a run of `workflow` may not go to the broker at this moment, or None: RUN_CANCELLED once
    the run was cancelled (`stop`), on any broker; for a real broker, its whole gate (RealBrokerGateRule) again, on the
    link, the user and the site's ordering switch as each is now. OrderExecution hands it to the broker, which asks it
    right before each send. OrderPreparation asked the same gate when it prepared the order; this asks again what may
    have changed since: the switch, the SinoPac server the settings on disk name, the user and the login.
    """
    link = execution_provider.link()
    refusal: tuple[RejectReason, str] | None = None

    if link.broker.real:
        user = await user_store.find(user_id) if user_id is not None else None
        refusal = gate_rule.apply(workflow, link.broker, link, user, await ordering_switch.read())

    # Asked after the reads above, with no await between it and the send, so a cancel during them stops the part too.
    if stop.is_set():
        return RejectReason.RUN_CANCELLED, "the run was cancelled before it was sent"

    return refusal


class OrderExecution:
    """
    Use Case: Send one recorded PENDING order to the broker and record the broker's answer; any other order comes back
    as it is, unsent. OrderPreparation recorded the order first, so a broker is never called for an order the journal
    does not hold. An order the broker call ends FAILED is a run error.

    The broker asks `refusal_now` right before each exchange order it sends, the second lot part of an order included:
    for a real broker, its whole gate (RealBrokerGateRule) on one read of the site's ordering switch at that moment and
    the user as saved then, so ordering turned off between the order's preparation and a part's send stops that part.

    A cancel (Ctrl-C, or WorkflowRuns.stop at shutdown) during the broker call sets the call's stop and lets the broker
    answer, and records that answer before it stops the run, so the journal never says PENDING about an order the
    broker saw. From then on the broker sends nothing more (`refusal_now` answers RUN_CANCELLED) and ends any wait
    for what it sent: what still works is cancelled at the broker and what dealt is read. A second cancel stops the
    broker call itself, so a part may have reached the broker and may still deal there: on a real broker the order is
    recorded UNCONFIRMED, which the broker's record of the day settles (OrderSettlement), and a second BUY of the stock
    waits for it (UnsettledBuyRule); on the mock account it is recorded FAILED with a reason that says to check it.
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
        self._refusal_now = partial(
            send_refusal, execution_provider, user_id, user_store, ordering_switch, config.broker_access_rule().gate_rule
        )
        self._logger = logger

    async def execute(self, order: Order, stats: SystemStats) -> Order:
        if order.status != OrderStatus.PENDING:
            return order

        stop = asyncio.Event()
        sending = asyncio.ensure_future(
            self._execution_provider.place_order(order, partial(self._refusal_now, stats.workflow, stop), stop)
        )
        run_cancelled = False

        try:
            await asyncio.wait([sending])
        except asyncio.CancelledError:
            run_cancelled = True
            stop.set()
            with contextlib.suppress(BaseException):
                await sending

        now = self._market_clock.now()
        if sending.cancelled() and order.status.is_open and self._execution_provider.link().broker.real:
            order.leave_unconfirmed(
                "the run was cancelled during the broker call, so the broker may hold this order: its record of the day settles it",
                now=now,
            )
        elif sending.cancelled():
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
