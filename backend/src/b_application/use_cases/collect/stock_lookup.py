from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.errors import ListingUnavailableError


class StockLookup:
    """
    Loads explicitly requested stock IDs for specific-stock analysis, the stock page and the manual watchlist: each ID
    once, in the order asked. An unknown ID is a run error, not an exception; an empty listing is an outage, which
    raises ListingUnavailableError rather than calling every ID unknown.
    """

    def __init__(self, stock_provider: IStockProvider, logger: ILoggingProvider) -> None:
        self._stock_provider = stock_provider
        self._logger = logger

    async def execute(self, stock_ids: list[str], stats: SystemStats) -> list[Stock]:
        listing = {stock.stock_id: stock for stock in await self._stock_provider.get_all()}

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
