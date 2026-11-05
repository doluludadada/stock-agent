from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository


class IntradayCandidates:
    """
    Loads Intraday's candidates: the held positions plus the active watchlist entries, each stock once, every watched
    stock carrying each type it is watched under. A watched stock the account holds is that held stock; an unknown one
    is a run error.
    """

    def __init__(self, stock_provider: IStockProvider, watchlist_repository: IWatchlistRepository, logger: ILoggingProvider) -> None:
        self._stock_provider = stock_provider
        self._watchlist_repository = watchlist_repository
        self._logger = logger

    async def execute(self, held_stocks: list[Stock], stats: SystemStats) -> list[Stock]:
        entries = await self._watchlist_repository.get_active()
        held = {stock.stock_id: stock for stock in held_stocks}
        watched_stocks: list[Stock] = []

        for stock_id in dict.fromkeys(entry.stock_id for entry in entries):
            stock = held.get(stock_id) or await self._stock_provider.get_by_id(stock_id)

            if stock is None:
                self._logger.warning(f"Stock not found: {stock_id}")
                stats.add_error(f"Stock not found: {stock_id}")
                continue

            stock.watchlist_types.update(entry.watchlist_type for entry in entries if entry.stock_id == stock_id)
            watched_stocks.append(stock)

        candidates = list({stock.stock_id: stock for stock in [*held_stocks, *watched_stocks]}.values())
        stats.total_scanned = len(candidates)

        self._logger.info(
            f"Intraday candidates loaded. Held={len(held_stocks)}, Watchlist={len(watched_stocks)}, Unique={len(candidates)}"
        )

        return candidates
