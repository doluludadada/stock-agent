from datetime import datetime, timedelta

from a_domain.model.market.stock import Stock
from a_domain.ports.analysis.indicator_provider import IIndicatorProvider
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.rules.process.policies.technical_screening import TechnicalScreeningPolicy
from a_domain.types.enums import CandidateSource, SignalReason
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


class Watchlist:
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
        self._stock = stock_provider
        self._market = market_provider
        self._watchlist = watchlist_repo
        self._tech_calc = tech_provider
        self._policy = screening_policy
        self._logger = logger
        self._config = config

    async def execute(self, context: PipelineContext) -> None:
        context.all_stocks = await self._stock.get_all()
        context.stats.total_scanned += len(context.all_stocks)
        self._logger.info(f"Generating technical watchlist from {len(context.all_stocks)} symbols...")

        survivors: list[Stock] = []
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self._config.analysis.lookback_days)

        history_map = await self._market.fetch_history(context.all_stocks, start_date, end_date)

        for stock in context.all_stocks:
            history = history_map.get(stock.stock_id, [])  # ? [] what's this?
            if not history:
                continue

            try:
                stock.source = CandidateSource.TECHNICAL_WATCHLIST
                stock.trigger_reason = SignalReason.NIGHTLY_SCREEN
                stock.ohlcv = history
                stock.indicators = self._tech_calc.calculate_indicators(history)
                self._policy.evaluate(stock)

                if not stock.is_eliminated:
                    survivors.append(stock)

            except Exception as e:
                self._logger.error(f"Scan error {stock.stock_id}: {e}")

        context.technical_watchlist = survivors
        context.stats.passed_technical += len(survivors)
        await self._watchlist.save_technical_watchlist(survivors)
        self._logger.info(f"Saved {len(survivors)} stocks to Technical Watchlist.")
