from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from a_domain.model.system.stats import SystemStats
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.enums import Workflow
from a_domain.types.ids import RunId, new_run_id
from b_application.config.app_config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class RunHistory:
    """
    Every workflow runs inside `execute`, which creates its PipelineStatus and saves the run record twice: when the
    run starts, and when it ends, normally or by an exception. A run whose record still has no end_time never
    finished. A failed save is logged in the run; the run goes on, because nothing acts on a decision whose own save
    failed.

    A caller that must name the run before it starts (the Web API answers with the run id at once) passes that id.
    """

    def __init__(self, journal: ITradingJournal, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider) -> None:
        self._journal = journal
        self._market_clock = market_clock
        self._execution_provider = config.trading.execution_provider
        self._order_mode = config.trading.order_mode
        self._logger = logger

    @asynccontextmanager
    async def execute(self, workflow: Workflow, run_id: RunId | None = None) -> AsyncIterator[PipelineStatus]:
        stats = SystemStats(
            run_id=run_id or new_run_id(),
            workflow=workflow,
            execution_provider=self._execution_provider,
            order_mode=self._order_mode,
            start_time=self._market_clock.now(),
        )

        try:
            await self._journal.save_run(stats)
        except Exception as error:
            self._logger.error(stats.add_error(f"Run record not saved: {stats.run_id}, error={error}"))

        try:
            yield PipelineStatus(stats=stats)
        except BaseException as error:
            stats.add_error(f"Run aborted: {type(error).__name__}: {error}")
            raise
        finally:
            stats.finish(now=self._market_clock.now())

            try:
                await self._journal.save_run(stats)
            except Exception as error:
                self._logger.error(stats.add_error(f"Run record not saved: {stats.run_id}, error={error}"))
