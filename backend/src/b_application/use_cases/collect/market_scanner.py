from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from b_application.schemas.pipeline_status import PipelineStatus


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

    async def execute(self, status: PipelineStatus) -> None:
        self._logger.info("Scanning full stock universe...")

        stocks = await self._stock_provider.get_all()

        status.universe_stocks = stocks
        status.stats.total_scanned = len(stocks)

        for stock in stocks:
            status.stocks_cache[stock.stock_id] = stock

        self._logger.info(f"Loaded {len(stocks)} universe stocks into analysis candidates.")

    async def find_stock_by_id(self, stock_id: str, status: PipelineStatus) -> Stock | None:
        stock_id = stock_id.strip()

        if not stock_id:
            return None

        if stock_id in status.stocks_cache:
            return status.stocks_cache[stock_id]

        stock = await self._stock_provider.get_by_id(stock_id)

        if stock is None:
            self._logger.warning(f"Stock not found: {stock_id}")
            return None

        status.stocks_cache[stock.stock_id] = stock
        return stock

    async def find_stocks_by_ids(
        self,
        stock_ids: list[str],
        status: PipelineStatus,
    ) -> list[Stock]:
        stocks: list[Stock] = []
        unique_stock_ids = dict.fromkeys(stock_id.strip() for stock_id in stock_ids if stock_id.strip())
        for stock_id in unique_stock_ids:
            stock = await self.find_stock_by_id(stock_id, status)

            if stock is None:
                status.stats.add_error(f"Stock not found: {stock_id}")
                continue

            stocks.append(stock)

        return stocks

    async def load_active_watchlist(
        self,
        status: PipelineStatus,
    ) -> StockWatchlist:
        active_watchlist = await self._watchlist_repository.get_active()
        watchlist_stocks = active_watchlist.willing_stocks

        if not watchlist_stocks:
            return active_watchlist

        stock_ids = [stock.stock_id for stock in watchlist_stocks]

        stocks = await self.find_stocks_by_ids(stock_ids=stock_ids, status=status)

        watchlist_types = {stock.stock_id: stock.watchlist_types for stock in watchlist_stocks}

        for stock in stocks:
            stock.watchlist_types.update(watchlist_types.get(stock.stock_id, set()))

        return StockWatchlist(willing_stocks=stocks)
