"""
Workflow Orchestrator.

Sequences the three phases of the stock analysis pipeline:
    Phase 1 (Nightly):   GenerateWatchlist  — scan universe, save technical watchlist
    Phase 2 (Morning):   ScanTrendingStocks — fetch social buzz, save buzz watchlist
    Phase 3 (Intraday):  Pipeline           — merge lists, filter, analyze, signal

Each phase can be invoked independently or as a full sequence.
"""

from backend.src.a_domain.model.system.stats import SystemStats
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.b_application.pipeline import Pipeline
from backend.src.b_application.use_cases.collect.market_scan import MarketScan
from backend.src.b_application.use_cases.collect.watchlist import Watchlist


class WorkflowOrchestrator:
    """
    Top-level orchestrator for the 3-phase trading workflow.

    ┌──────────┐     ┌──────────────┐     ┌──────────────────┐
    │ Phase 1  │ ──▶ │   Phase 2    │ ──▶ │    Phase 3       │
    │ Nightly  │     │  Buzz Scan   │     │ Intraday Pipeline│
    │ Watchlist│     │  (optional)  │     │ (execute trades) │
    └──────────┘     └──────────────┘     └──────────────────┘
    """

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

    async def run_full_cycle(self, manual_symbols: list[str] | None = None) -> SystemStats:
        """Execute all three phases in sequence. Returns intraday stats."""
        await self.run_nightly()
        await self.run_buzz_scan()
        return await self.run_intraday(manual_symbols)

    async def run_nightly(self) -> None:
        """Phase 1: Generate technical watchlist from universe scan."""
        self._logger.info("=== Phase 1: Nightly Watchlist Generation ===")
        try:
            stats = await self._watchlist.execute()
            self._logger.info(f"Nightly done. Passed: {stats.passed_technical}/{stats.total_candidates}")
        except Exception as e:
            self._logger.exception(f"Phase 1 failed: {e}")

    async def run_buzz_scan(self) -> None:
        """Phase 2: Scan social media for trending stocks."""
        self._logger.info("=== Phase 2: Social Buzz Scan ===")
        try:
            stats = await self._market_scan.execute()
            self._logger.info(f"Buzz scan done. Found: {stats.total_candidates}")
        except Exception as e:
            self._logger.exception(f"Phase 2 failed: {e}")

    async def run_intraday(self, manual_symbols: list[str] | None = None) -> SystemStats:
        """Phase 3: Execute intraday analysis and signal generation."""
        self._logger.info("=== Phase 3: Intraday Pipeline ===")
        try:
            return await self._pipeline.execute(manual_symbols)
        except Exception as e:
            self._logger.exception(f"Phase 3 failed: {e}")
            stats = SystemStats()
            stats.add_error(f"Intraday pipeline failed: {e}")
            return stats
