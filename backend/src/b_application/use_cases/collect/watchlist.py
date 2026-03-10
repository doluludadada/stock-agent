"""
Use Case: Generate the nightly technical watchlist.
Phase 1: Scans market history -> Saves to Technical Watchlist (DB).
"""
from datetime import datetime, timedelta

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.ports.analysis.indicator_provider import IIndicatorProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.rules.process.policies.technical_screening import TechnicalScreeningPolicy
from a_domain.types.enums import CandidateSource, SignalReason
from b_application.schemas.config import AppConfig


class Watchlist:
    """Phase 1: Scans market history -> Saves to Technical Watchlist (DB)."""

    def __init__(
        self,
        stock_provider: IStockProvider,
        market_provider: IPriceProvider,
        watchlist_repo: IWatchlistRepository,
        tech_provider: IIndicatorProvider,
        screening_policy: TechnicalScreeningPolicy,
        logger: ILoggingProvider,
        config: AppConfig,
    ):
        self._stock_list = stock_provider
        self._market = market_provider
        self._watchlist = watchlist_repo
        self._tech_calc = tech_provider
        self._policy = screening_policy
        self._logger = logger
        self._config = config

    async def execute(self) -> SystemStats:
        stats = SystemStats()

        universe = await self._stock_list.get_all()
        stats.total_scanned = len(universe)
        self._logger.info(f"Generating technical watchlist from {len(universe)} symbols...")

        passed_stocks = []
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self._config.analysis_lookback_days)

        for stock in universe:
            try:
                history = await self._market.fetch_history(stock.stock_id, start_date, end_date)
                if not history:
                    continue

                indicators = self._tech_calc.calculate_indicators(history)

                pipeline_stock = Stock(
                    stock_id=stock.stock_id, market=stock.market, name=stock.name,
                    industry=stock.industry, source=CandidateSource.TECHNICAL_WATCHLIST,
                    trigger_reason=SignalReason.NIGHTLY_SCREEN, ohlcv=history, indicators=indicators,
                )

                self._policy.evaluate(pipeline_stock, is_intraday=False)

                if not pipeline_stock.is_eliminated:
                    passed_stocks.append(stock)
            except Exception as e:
                self._logger.error(f"Scan error {stock.stock_id}: {e}")

        await self._watchlist.save_technical_watchlist(passed_stocks)
        stats.passed_technical = len(passed_stocks)
        self._logger.info(f"Saved {len(passed_stocks)} stocks to Technical Watchlist.")
        return stats
