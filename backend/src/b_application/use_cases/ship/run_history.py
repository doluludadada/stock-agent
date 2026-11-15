from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from a_domain.model.system.stats import SystemStats
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.enums import AiProvider, ExecutionProvider, Workflow
from a_domain.types.ids import RunId, new_run_id
from b_application.config.app_config import AppConfig


class RunHistory:
    """
    Every workflow runs inside `execute`, which yields the run's SystemStats and saves them as the run record twice:
    when the run starts, and when it ends, normally or by an exception. A run whose record still has no end_time never
    finished; one that ended by an exception keeps it as its failure. A run whose first save fails never starts: the
    journal reads each order and snapshot through its run's record, so an unrecorded run's orders would be missing
    from its broker's account and from the day's total of BUYs on it. A failed last save is logged in the run.

    A caller that must name the run before it starts (the Web API answers with the run id at once) passes that id. A
    follow names the run it follows, and a run the site's schedule started says so.
    `ai_model` is the AI model the Pipeline's AI provider runs on, so the record names the model the run used, and
    `broker` the broker its ordering steps hold, the run's choice, which the record keeps for the run's whole life.
    """

    def __init__(
        self,
        journal: ITradingJournal,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
        ai_model: AiProvider,
        broker: ExecutionProvider,
    ) -> None:
        self._journal = journal
        self._market_clock = market_clock
        self._broker = broker
        self._ai_model = config.ai.available_models.get(ai_model)
        self._logger = logger

    @asynccontextmanager
    async def execute(
        self, workflow: Workflow, run_id: RunId | None = None, followed_run_id: RunId | None = None, *, scheduled: bool = False
    ) -> AsyncGenerator[SystemStats]:
        stats = SystemStats(
            run_id=run_id or new_run_id(),
            workflow=workflow,
            followed_run_id=followed_run_id,
            scheduled=scheduled,
            execution_provider=self._broker,
            ai_model=self._ai_model,
            start_time=self._market_clock.now(),
        )

        await self._journal.save_run(stats)

        try:
            yield stats
        except BaseException as error:
            stats.failure = f"{type(error).__name__}: {error}"
            stats.add_error(f"Run aborted: {stats.failure}")
            raise
        finally:
            stats.finish(now=self._market_clock.now())
            try:
                await self._journal.save_run(stats)
            except Exception as error:
                self._logger.error(stats.add_error(f"Run record not saved: {stats.run_id}, error={error}"))
            self._logger.info(f"Run {workflow.value} finished. Signals={stats.signals_generated}, Orders={stats.orders_submitted}.")
