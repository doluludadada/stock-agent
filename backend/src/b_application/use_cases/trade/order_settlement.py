import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.order import Order
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IBrokerExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.execution import LotSplitRule, PastSessionRule
from a_domain.types.enums import ExecutionProvider
from b_application.config.app_config import AppConfig


class OrderSettlement:
    """
    Use Case: Settle the orders the site's real broker took whose outcome the site could not read when they were sent
    (UNCONFIRMED), from the broker's own record of the day (IBrokerExecutionProvider.settle): what still works of them
    is cancelled, what they dealt is recorded and saved, and each ends with the status that record gives it
    (BrokerOutcomeRule), or stays UNCONFIRMED while the record cannot tell yet.

    Given a run's `stats` and its own `orders`, at its end, it settles those and answers them, each as it stands now.
    Given the stats alone, before the run sends anything, it settles the journal's orders of every run on the broker
    that ended, never of a run still under way, whose parts may be in flight, so the account the run sizes on and the
    day's BUY limit see what the broker did; and answers those. A run on another broker (the mock account) settles
    nothing. Without stats, on the Web API's timer, it settles the journal's on the site's real broker whoever's
    Pipeline it is, whatever the user may hold now: it only reads and cancels what their own journal holds of it.
    `brokerage` is the site's real broker, None where it has none, the timer's broker the audience's real broker, and a
    run's broker the one its record names. An order of an earlier session is never in the broker's record of the day:
    it fails with what it recorded (PastSessionRule) whether the login is up, down or missing, so none awaits
    settlement past the next day. Any other asks the broker, and waits while the login is down or the site has none.
    A settlement asks the broker nothing, its link included, while no order awaits settlement. An order whose record
    could not be read stays as it was, for the next settlement, and the error is the run's. One settlement of a broker
    runs at a time in the process (`locks`, the process's), so the timer's and a run's never interleave their saves of
    the same order. An order is logged at INFO only when the settlement changed its status.
    """

    def __init__(
        self,
        brokerage: IBrokerExecutionProvider[Any, Any] | None,
        journal: ITradingJournal,
        locks: Mapping[ExecutionProvider, asyncio.Lock],
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._brokerage = brokerage
        self._journal = journal
        self._locks = locks
        self._market_clock = market_clock
        self._real_broker = config.audience.real_broker
        self._past_session_rule = PastSessionRule(lot_split_rule=LotSplitRule(board_lot_shares=config.market.board_lot_shares))
        self._logger = logger

    async def execute(self, stats: SystemStats | None, orders: Sequence[Order] | None = None) -> list[Order]:
        broker = self._real_broker if stats is None else stats.execution_provider

        if broker is None or not broker.real:
            return list(orders or [])

        async with self._locks[broker]:
            held = list(orders) if orders is not None else await self._journal.unsettled_orders(broker)
            unsettled, today = [order for order in held if order.status.awaits_settlement], self._market_clock.today()

            for order in unsettled:
                settling, session = replace(order), self._market_clock.to_trading_date(order.created_at)

                try:
                    if (lapsed := self._past_session_rule.apply(order, broker, session, today)) is not None:
                        settling.fail(lapsed, now=self._market_clock.now())
                    elif self._brokerage is not None and self._brokerage.link().up:
                        await self._brokerage.settle(settling)
                    else:
                        continue

                    await self._journal.save_order(settling)
                except Exception as error:
                    message = f"Order {order.id} still awaits settlement at {broker.label}: {type(error).__name__}: {error}"
                    self._logger.error(stats.add_error(message) if stats is not None else message)
                    continue

                if settling.status != order.status:
                    self._logger.info(f"Order {order.id} on {broker.label} settled: {settling.summary}")

                held = [settling if kept.id == order.id else kept for kept in held]

        return held
