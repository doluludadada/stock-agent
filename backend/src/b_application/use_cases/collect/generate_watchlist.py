from datetime import datetime, timedelta

from backend.src.a_domain.model.analysis.analysis_context import AnalysisContext
from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.model.system.stats import SystemStats
from backend.src.a_domain.ports.analysis.technical_analysis_provider import ITechnicalAnalysisProvider
from backend.src.a_domain.ports.input.watchlist_repository import IWatchlistRepository
from backend.src.a_domain.ports.market.market_data_provider import IMarketDataProvider
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.a_domain.rules.process.policies.technical_screening import TechnicalScreeningPolicy
from backend.src.a_domain.types.constants import REASON_NIGHTLY_SCREEN
from backend.src.a_domain.types.enums import CandidateSource


class GenerateWatchlist:
    """
    Phase 1: Scans market history -> Saves to Technical Watchlist (DB).
    """

    def __init__(
        self,
        market_provider: IMarketDataProvider,
        watchlist_repo: IWatchlistRepository,
        tech_provider: ITechnicalAnalysisProvider,
        screening_policy: TechnicalScreeningPolicy,
        logger: ILoggingProvider,
        lookback_days: int = 120,
    ):
        self._market = market_provider
        self._watchlist = watchlist_repo
        self._tech_calc = tech_provider
        self._policy = screening_policy
        self._logger = logger
        self._lookback_days = lookback_days

    async def execute(self, universe: list[Stock]) -> SystemStats:
        stats = SystemStats()
        stats.total_candidates = len(universe)
        self._logger.info(f"Generating technical watchlist from {len(universe)} symbols...")

        passed_stocks: list[Stock] = []
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self._lookback_days)

        for stock in universe:
            try:
                history = await self._market.fetch_history(stock.stock_id, start_date, end_date)
                if not history:
                    continue

                # 1. Update calculation call
                indicators = self._tech_calc.calculate_indicators(history)

                ctx = AnalysisContext(
                    stock=stock,
                    source=CandidateSource.TECHNICAL_WATCHLIST,
                    trigger_reason=REASON_NIGHTLY_SCREEN,
                    ohlcv_data=history,
                    current_price=history[-1].close_price if history else None,
                    indicators=indicators,  # 2. Pass aggregate
                )

                if not self._policy.evaluate(ctx):
                    passed_stocks.append(stock)

            except Exception as e:
                self._logger.error(f"Scan error {stock.stock_id}: {e}")

        # Save to Technical Bucket
        await self._watchlist.save_technical_watchlist(passed_stocks)

        stats.passed_technical = len(passed_stocks)
        self._logger.success(f"Saved {len(passed_stocks)} stocks to Technical Watchlist.")
        return stats


