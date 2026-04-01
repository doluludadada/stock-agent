"""
Workflow Orchestrator.

Phase 1 (Nightly):   Watchlist      - scan universe, save technical watchlist
Phase 2 (Morning):   MarketScan     - fetch social buzz, save buzz watchlist
Phase 3 (Intraday):  Pipeline       - merge lists, filter, analyze, signal
"""

from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.pipeline import Pipeline
from b_application.schemas.pipeline_context import PipelineContext
from b_application.use_cases.collect.market_scan import MarketScan
from b_application.use_cases.collect.watchlist import Watchlist


class WorkflowOrchestrator:
    def __init__(
        self,
        watchlist: Watchlist,
        market_scan: MarketScan,
        intraday_pipeline: Pipeline,
        logger: ILoggingProvider,
        db=None,
    ):
        self._watchlist = watchlist
        self._market_scan = market_scan
        self._pipeline = intraday_pipeline
        self._logger = logger
        self._db = db

    async def shutdown(self) -> None:
        """Cleanup resources on exit."""
        if self._db:
            self._logger.info("Shutting down workflow resources...")
            await self._db.close()

    async def run_full_cycle(self, manual_symbols: list[str] | None = None) -> PipelineContext:
        workflow_state = PipelineContext(manual_symbols=manual_symbols or [])
        await self.run_nightly(workflow_state)
        await self.run_buzz_scan(workflow_state)
        await self.run_intraday(workflow_state)
        workflow_state.stats.finish()
        return workflow_state

    async def run_nightly(self, workflow_state: PipelineContext) -> None:
        self._logger.info("=== Phase 1: Nightly Watchlist Generation ===")
        try:
            await self._watchlist.execute(workflow_state)
            self._logger.info(f"Nightly done. Passed: {len(workflow_state.technical_watchlist)}/{len(workflow_state.all_stocks)}")
        except Exception as e:
            self._logger.exception(f"Phase 1 failed: {e}")
            workflow_state.stats.add_error(f"Phase 1 failed: {e}")

    async def run_buzz_scan(self, workflow_state: PipelineContext) -> None:
        self._logger.info("=== Phase 2: Social Buzz Scan ===")
        try:
            await self._market_scan.execute(workflow_state)
            self._logger.info(f"Buzz scan done. Found: {len(workflow_state.buzz_watchlist)} trending stocks")
        except Exception as e:
            self._logger.exception(f"Phase 2 failed: {e}")
            workflow_state.stats.add_error(f"Phase 2 failed: {e}")

    async def run_intraday(self, workflow_state: PipelineContext) -> None:
        self._logger.info("=== Phase 3: Intraday Pipeline ===")
        try:
            await self._pipeline.execute(workflow_state)
        except Exception as e:
            self._logger.exception(f"Phase 3 failed: {e}")
            workflow_state.stats.add_error(f"Intraday pipeline failed: {e}")
