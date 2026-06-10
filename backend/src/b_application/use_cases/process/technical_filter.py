# backend/src/b_application/use_cases/process/technical_filter.py


from icontract import ensure

from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import WatchlistType
from b_application.factories import TechnicalPolicyFactory
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


class TechnicalFilter:
    """
    Use Case: Apply technical rules to stocks with precomputed indicators.
    """

    def __init__(self, config: AppConfig, logger: ILoggingProvider):
        self._logger = logger
        self._policy = TechnicalPolicyFactory().create(config.analysis.active_strategy, config.strategy)

    @ensure(
        lambda context, watchlist_type: watchlist_type is None or len(context.watchlist) == len(context.survivors),
        "Watchlist entries should match technical survivors",
    )
    @ensure(
        lambda context, watchlist_type: watchlist_type is None or all(entry.type == watchlist_type for entry in context.watchlist),
        "Watchlist entries should use the requested type",
    )
    async def execute(
        self,
        context: PipelineContext,
        watchlist_type: WatchlistType | None = None,
    ) -> None:
        self._logger.info(f"Filtering {len(context.all_stocks)} stocks.")

        surviving_stocks = []

        for stock in context.all_stocks:
            # 1. Rule: Apply the technical screening rules
            self._policy.evaluate(stock)

            # 2. Decision: If it didn't get a hard failure, it survives!
            if not stock.is_eliminated:
                surviving_stocks.append(stock)

        # Update the context with only the stocks that passed
        context.survivors = surviving_stocks

        if watchlist_type is not None:
            context.watchlist = [
                StockWatchlist(
                    stock_id=stock.stock_id,
                    type=watchlist_type,
                )
                for stock in surviving_stocks
            ]

        self._logger.success(f"{len(surviving_stocks)} stocks passed technical filter.")
