"""
Use Case: Generate the nightly technical watchlist.

Phase 1: Scans market history -> Saves to Technical Watchlist (DB).
"""

from datetime import datetime, timedelta

from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.model.system.stats import SystemStats
from backend.src.a_domain.ports.analysis.indicator_provider import IIndicatorProvider
from backend.src.a_domain.ports.input.stock_provider import IStockProvider
from backend.src.a_domain.ports.input.watchlist_repository import IWatchlistRepository
from backend.src.a_domain.ports.market.market_provider import IMarketProvider
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.a_domain.rules.process.policies.technical_screening import TechnicalScreeningPolicy
from backend.src.a_domain.types.constants import REASON_NIGHTLY_SCREEN
from backend.src.a_domain.types.enums import CandidateSource


class Watchlist:
    """Phase 1: Scans market history -> Saves to Technical Watchlist (DB)."""

    def __init__(
        self,
        stock_provider: IStockProvider,
        market_provider: IMarketProvider,
        watchlist_repo: IWatchlistRepository,
        tech_provider: IIndicatorProvider,
        screening_policy: TechnicalScreeningPolicy,
        logger: ILoggingProvider,
        lookback_days: int = 120,
    ):
        self._stock_list = stock_provider
        self._market = market_provider
        self._watchlist = watchlist_repo
        self._tech_calc = tech_provider
        self._policy = screening_policy
        self._logger = logger
        self._lookback_days = lookback_days

    async def execute(self) -> SystemStats:
        stats = SystemStats()

        universe = await self._stock_list.get_all()
        stats.total_candidates = len(universe)
        self._logger.info(f"Generating technical watchlist from {len(universe)} symbols...")

        passed_stocks = []
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self._lookback_days)

        for stock in universe:
            try:
                history = await self._market.fetch_history(stock.stock_id, start_date, end_date)
                if not history:
                    continue

                indicators = self._tech_calc.calculate_indicators(history)

                candidate = Stock(
                    stock_id=stock.stock_id,
                    market=stock.market,
                    name=stock.name,
                    industry=stock.industry,
                    source=CandidateSource.TECHNICAL_WATCHLIST,
                    trigger_reason=REASON_NIGHTLY_SCREEN,
                    ohlcv_data=history,
                    indicators=indicators,
                )

                # Nightly: is_intraday=False skips entry timing rules
                self._policy.evaluate(candidate, is_intraday=False)

                if not candidate.is_eliminated:
                    passed_stocks.append(stock)

            except Exception as e:
                self._logger.error(f"Scan error {stock.stock_id}: {e}")

        await self._watchlist.save_technical_watchlist(passed_stocks)

        stats.passed_technical = len(passed_stocks)
        self._logger.info(f"Saved {len(passed_stocks)} stocks to Technical Watchlist.")
        return stats
