from a_domain.model.market.stock import Stock
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from b_application.schemas.pipeline_context import PipelineContext


class MarketScanner:
    """
    Loads stock candidates for trading workflows.

    Full cycle:
        Loads the full universe into universe_stocks and analysis_candidates.

    Manual analysis:
        Loads explicitly requested stock IDs into analysis_candidates.

    Intraday:
        Loads held positions plus active watchlist entries into analysis_candidates.
    """

    def __init__(
        self,
        stock_provider: IStockProvider,
        watchlist_repository: IWatchlistRepository,
        logger: ILoggingProvider,
    ) -> None:
        self._stock_provider = stock_provider
        self._watchlist_repository = watchlist_repository
        self._logger = logger

    async def execute(self, context: PipelineContext) -> None:
        self._logger.info("Scanning full stock universe...")

        stocks = await self._stock_provider.get_all()

        context.universe_stocks = stocks
        context.stats.total_scanned = len(stocks)

        for stock in stocks:
            context.stocks_cache[stock.stock_id] = stock

        self._logger.info(f"Loaded {len(stocks)} universe stocks into analysis candidates.")

    async def execute_by_ids(
        self,
        stock_ids: list[str],
        context: PipelineContext,
    ) -> list[Stock]:
        self._logger.info(f"Loading requested stocks: {stock_ids}")

        stocks: list[Stock] = []

        for stock_id in dict.fromkeys(stock_ids):
            stock = context.stocks_cache.get(stock_id)

            if stock is None:
                stock = await self._stock_provider.get_by_id(stock_id)

            if stock is None:
                self._logger.warning(f"Stock not found: {stock_id}")
                continue

            context.stocks_cache[stock.stock_id] = stock
            stocks.append(stock)

        return stocks