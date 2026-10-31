from a_domain.model.market.stock import Stock
from a_domain.model.trading.stock_watchlist import StockWatchlist
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from b_application.schemas.pipeline_status import PipelineStatus


class IntradayCandidates:
    """
    Loads Intraday's candidates: the held positions plus the active watchlist entries, each stock once.

    The active watchlist becomes status.watchlist, each stock carrying every type it is watched under.
    A watched stock this run already loaded is reused; an unknown one is a run error.
    """

    def __init__(self, stock_provider: IStockProvider, watchlist_repository: IWatchlistRepository, logger: ILoggingProvider) -> None:
        self._stock_provider = stock_provider
        self._watchlist_repository = watchlist_repository
        self._logger = logger

    async def execute(self, status: PipelineStatus) -> list[Stock]:
        watched_stocks: list[Stock] = []

        for watched in StockWatchlist.from_entries(await self._watchlist_repository.get_active()).willing_stocks:
            stock = status.stocks_cache.get(watched.stock_id) or await self._stock_provider.get_by_id(watched.stock_id)

            if stock is None:
                self._logger.warning(f"Stock not found: {watched.stock_id}")
                status.stats.add_error(f"Stock not found: {watched.stock_id}")
                continue

            stock.watchlist_types.update(watched.watchlist_types)
            status.stocks_cache[stock.stock_id] = stock
            watched_stocks.append(stock)

        status.watchlist = StockWatchlist(willing_stocks=watched_stocks)
        candidates = list({stock.stock_id: stock for stock in [*status.held_stocks, *watched_stocks]}.values())

        self._logger.info(
            f"Intraday candidates loaded. Held={len(status.held_stocks)}, Watchlist={len(watched_stocks)}, Unique={len(candidates)}"
        )

        return candidates
