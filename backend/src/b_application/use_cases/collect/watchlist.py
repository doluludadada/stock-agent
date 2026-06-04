# backend/src/b_application/use_cases/collect/watchlist.py

from datetime import datetime, timedelta

from a_domain.model.market.stock import Stock
from a_domain.ports.analysis.indicator_provider import IIndicatorProvider
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.rules.technical.policy import TechnicalScreeningPolicy
from a_domain.types.enums import CandidateSource
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


class Watchlist:
    """
    Use Case: Build nightly technical watchlist.

    This phase scans the full universe and stores technical candidates for intraday selection.
    """

    def __init__(
        self,
        stock_provider: IStockProvider,
        price_provider: IPriceProvider,
        watchlist_repo: IWatchlistRepository,
        indicator_provider: IIndicatorProvider,
        screening_policy: TechnicalScreeningPolicy,
        logger: ILoggingProvider,
        config: AppConfig,
    ):
        self._stock = stock_provider
        self._price = price_provider
        self._watchlist = watchlist_repo
        self._indicator = indicator_provider
        self._policy = screening_policy
        self._logger = logger
        self._config = config


    async def execute(self, context: PipelineContext) -> None:
        context.all_stocks = await self._stock.get_all()
        context.stats.total_scanned += len(context.all_stocks)

        self._logger.info(f"Generating technical watchlist from {len(context.all_stocks)} symbols.")
        survivors: list[Stock] = []
        """
        Stocks that pass the nightly screening policy.
        """

        end_date = datetime.now()
        """
        Last day of the historical window.
        """

        start_date = end_date - timedelta(days=self._config.analysis.lookback_days)
        """
        First day of the historical window.
        """

        # Bulk stock_id -> historical OHLCV mapping.
        history_map = await self._price.fetch_history(
            context.all_stocks,
            start_date,
            end_date,
        )

        for stock in context.all_stocks:
            # Empty history means the stock cannot be technically evaluated.
            history = history_map.get(stock.stock_id, [])

            if not history:
                continue

            try:
                stock.source = CandidateSource.TECHNICAL_WATCHLIST
                # TODO: Why there's hard code
                stock.trigger_reason = "Nightly Technical Scan"
                stock.ohlcv = history
                stock.indicators = self._indicator.calculate_indicators(history)

                self._policy.evaluate(stock)

                if not stock.is_eliminated:
                    survivors.append(stock)

            except Exception as e:
                error_message = f"Scan error {stock.stock_id}: {e}"
                self._logger.error(error_message)
                context.stats.add_error(error_message)

        context.technical_watchlist = survivors
        context.stats.passed_technical += len(survivors)

        await self._watchlist.save_technical_watchlist(survivors)

        self._logger.info(f"Saved {len(survivors)} stocks to Technical Watchlist.")
