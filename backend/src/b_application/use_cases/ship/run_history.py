from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from a_domain.model.system.stats import SystemStats
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.enums import Workflow
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class RunHistory:
    """
    Every workflow runs inside `open`, which creates its PipelineStatus and saves the run record
    twice: when the run starts, and when it ends, normally or by an exception. A run whose record
    still has no end_time never finished. A failed save is logged in the run; the run goes on,
    because nothing acts on a decision whose own save failed.
    """

    def __init__(self, journal: ITradingJournal, config: AppConfig, logger: ILoggingProvider) -> None:
        self._journal = journal
        self._config = config
        self._logger = logger

    @asynccontextmanager
    async def open(self, workflow: Workflow) -> AsyncIterator[PipelineStatus]:
        stats = SystemStats(
            workflow=workflow, execution_provider=self._config.trading.execution_provider, order_mode=self._config.trading.order_mode
        )
        await self._save(stats)

        try:
            yield PipelineStatus(stats=stats)

        except BaseException as error:
            stats.add_error(f"Run aborted: {type(error).__name__}: {error}")
            raise

        finally:
            stats.finish()
            await self._save(stats)

    async def _save(self, stats: SystemStats) -> None:
        try:
            await self._journal.save_run(stats)

        except Exception as error:
            message = f"Run record not saved: {stats.run_id}, error={error}"
            self._logger.error(message)
            stats.add_error(message)
