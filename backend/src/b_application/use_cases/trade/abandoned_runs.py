from datetime import datetime
from typing import Any

from a_domain.model.system.stats import SystemStats
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IBrokerExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal


class AbandonedRuns:
    """
    Use Case: End the runs on the site's real broker that an earlier process left without an end (a hard kill, or a
    run whose last save failed), so their orders are settled. A run that started before this process (`process_started`)
    and never ended is no run of this process; its open orders (PENDING or SUBMITTED, whatever the broker did with them)
    may have reached the broker, so each becomes UNCONFIRMED, which the broker's record of the day settles
    (OrderSettlement), and the run ends with a failure that says its process stopped. The orders are saved before the
    run, so one that could not be saved leaves the run open for the next look. A run of another process that started
    after this one, such as a CLI's beside the Web API, is never touched. One that started before and is still under
    way is ended too, since nothing tells it from one a stopped process left: a CLI run on SinoPac that began before the
    Web API, or the runs of another worker of the Web API. Only the Web API's timer asks, so the Web API starts while no
    CLI run on SinoPac is under way (README), and it runs as one process with one uvicorn worker (backend/main.py).
    Nothing on the mock account.
    """

    def __init__(
        self,
        brokerage: IBrokerExecutionProvider[Any, Any] | None,
        journal: ITradingJournal,
        market_clock: IMarketClock,
        process_started: datetime,
        logger: ILoggingProvider,
    ) -> None:
        self._brokerage = brokerage
        self._journal = journal
        self._market_clock = market_clock
        self._process_started = process_started
        self._logger = logger

    async def execute(self) -> list[SystemStats]:
        if self._brokerage is None:
            return []

        broker = self._brokerage.link().broker
        runs = await self._journal.unfinished_runs(broker, self._process_started)

        for run in runs:
            now = self._market_clock.now()

            for order in await self._journal.orders_of(run.run_id):
                if order.status.is_open and not order.status.awaits_settlement:
                    order.leave_unconfirmed(f"its run's process stopped before it read {broker.label}'s answer", now=now)
                    await self._journal.save_order(order)

            run.failure = "the process that ran it stopped before the run ended"
            run.finish(now=now)
            await self._journal.save_run(run)
            self._logger.warning(
                f"Run {run.run_id} on {broker.label}, left by a process that stopped, ended: its orders await settlement"
            )

        return runs
