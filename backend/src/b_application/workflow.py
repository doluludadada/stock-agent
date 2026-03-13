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
    ):
        self._watchlist = watchlist
        self._market_scan = market_scan
        self._pipeline = intraday_pipeline
        self._logger = logger

    async def run_full_cycle(self, manual_symbols: list[str] | None = None) -> PipelineContext:
        ctx = PipelineContext(manual_symbols=manual_symbols or [])
        await self.run_nightly(ctx)
        await self.run_buzz_scan(ctx)
        await self.run_intraday(ctx)
        ctx.stats.finish()
        return ctx

    async def run_nightly(self, ctx: PipelineContext) -> None:
        """Phase 1: Generate technical watchlist from universe scan."""
        self._logger.info("=== Phase 1: Nightly Watchlist Generation ===")
        try:
            await self._watchlist.execute(ctx)
            self._logger.info(f"Nightly done. Passed: {len(ctx.technical_watchlist)}/{len(ctx.universe)}")
        except Exception as e:
            self._logger.exception(f"Phase 1 failed: {e}")
            ctx.stats.add_error(f"Phase 1 failed: {e}")

    async def run_buzz_scan(self, ctx: PipelineContext) -> None:
        """Phase 2: Scan social media for trending stocks."""
        self._logger.info("=== Phase 2: Social Buzz Scan ===")
        try:
            await self._market_scan.execute(ctx)
            self._logger.info(f"Buzz scan done. Found: {len(ctx.buzz_watchlist)} trending stocks")
        except Exception as e:
            self._logger.exception(f"Phase 2 failed: {e}")
            ctx.stats.add_error(f"Phase 2 failed: {e}")

    async def run_intraday(self, ctx: PipelineContext) -> None:
        """Phase 3: Execute intraday analysis and signal generation."""
        self._logger.info("=== Phase 3: Intraday Pipeline ===")
        try:
            await self._pipeline.execute(ctx)
        except Exception as e:
            self._logger.exception(f"Phase 3 failed: {e}")
            ctx.stats.add_error(f"Intraday pipeline failed: {e}")
