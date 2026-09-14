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
        Loads the full universe into universe_stocks.

    Manual analysis:
        Loads explicitly requested stock IDs.

    Intraday:
        Loads held positions plus active watchlist entries.
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
        source_stocks = await self._stock_provider.get_all()
        stocks = [
            stock.model_copy(deep=True)
            for stock in source_stocks
        ]

        status.universe_stocks = stocks
        status.stats.total_scanned = len(stocks)

        for stock in stocks:
            stock.realtime_bar = None
            status.stocks_cache[stock.stock_id] = stock

        self._logger.info(
            f"Loaded {len(stocks)} universe stocks into analysis candidates."
        )

    async def find_stock_by_id(
        self,
        stock_id: str,
        status: PipelineStatus,
    ) -> Stock | None:
        stock_id = stock_id.strip()

        if not stock_id:
            return None

        cached_stock = status.stocks_cache.get(stock_id)

        if cached_stock is not None:
            return cached_stock

        source_stock = await self._stock_provider.get_by_id(stock_id)

        if source_stock is None:
            self._logger.warning(f"Stock not found: {stock_id}")
            return None

        stock = source_stock.model_copy(deep=True)
        stock.realtime_bar = None
        status.stocks_cache[stock.stock_id] = stock

        return stock

    async def find_stocks_by_ids(
        self,
        stock_ids: list[str],
        status: PipelineStatus,
    ) -> list[Stock]:
        stocks: list[Stock] = []
        unique_stock_ids = dict.fromkeys(
            stock_id.strip()
            for stock_id in stock_ids
            if stock_id.strip()
        )

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

        stock_ids = [
            stock.stock_id
            for stock in watchlist_stocks
        ]
        stocks = await self.find_stocks_by_ids(
            stock_ids=stock_ids,
            status=status,
        )
        watchlist_types = {
            stock.stock_id: stock.watchlist_types
            for stock in watchlist_stocks
        }

        for stock in stocks:
            stock.watchlist_types.update(
                watchlist_types.get(stock.stock_id, set())
            )

        return StockWatchlist(willing_stocks=stocks)

    async def load_intraday_candidates(
        self,
        status: PipelineStatus,
    ) -> list[Stock]:
        status.watchlist = await self.load_active_watchlist(status)

        candidates = {
            stock.stock_id: stock
            for stock in status.held_stocks
        }

        for stock in status.watchlist.willing_stocks:
            candidates[stock.stock_id] = stock

        stocks = list(candidates.values())

        self._logger.info(
            f"Intraday candidates loaded. "
            f"Held={len(status.held_stocks)}, "
            f"Watchlist={len(status.watchlist.willing_stocks)}, "
            f"Unique={len(stocks)}"
        )

        return stocks
