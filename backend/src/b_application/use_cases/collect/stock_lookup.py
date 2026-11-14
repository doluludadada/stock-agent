from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.errors import ListingUnavailableError


class StockLookup:
    """
    Loads stocks from the exchange listing, each a new copy. Given None, it is the full stock universe, every listed
    and OTC stock, counted as the run's scanned stocks: an outage leaves it empty, which ends a run with nothing and
    leaves a page's stocks unnamed. Given stock IDs, for specific-stock analysis, the stock page and the manual
    watchlist, it is each ID once, in the order asked: an unknown ID is a run error, not an exception, and an empty
    listing is an outage, which raises ListingUnavailableError rather than calling every ID unknown.
    """

    def __init__(self, stock_provider: IStockProvider, logger: ILoggingProvider) -> None:
        self._stock_provider = stock_provider
        self._logger = logger

    async def execute(self, stock_ids: list[str] | None, stats: SystemStats) -> list[Stock]:
        universe = await self._stock_provider.get_all()

        if stock_ids is None:
            stats.total_scanned = len(universe)
            self._logger.info(f"Loaded {len(universe)} universe stocks into analysis candidates.")
            return universe

        listing = {stock.stock_id: stock for stock in universe}

        if not listing:
            raise ListingUnavailableError("The TWSE and TPEX listings could not be loaded.")

        stocks: list[Stock] = []

        for stock_id in dict.fromkeys(stock_id.strip() for stock_id in stock_ids if stock_id.strip()):
            stock = listing.get(stock_id)

            if stock is None:
                self._logger.warning(f"Stock not found: {stock_id}")
                stats.add_error(f"Stock not found: {stock_id}")
                continue

            stocks.append(stock)

        return stocks
