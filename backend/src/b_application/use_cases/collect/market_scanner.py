from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider


class MarketScanner:
    """Loads the full stock universe: every listed and OTC stock, each a new copy."""

    def __init__(self, stock_provider: IStockProvider, logger: ILoggingProvider) -> None:
        self._stock_provider = stock_provider
        self._logger = logger

    async def execute(self, stats: SystemStats) -> list[Stock]:
        self._logger.info("Scanning full stock universe...")
        stocks = await self._stock_provider.get_all()
        stats.total_scanned = len(stocks)

        self._logger.info(f"Loaded {len(stocks)} universe stocks into analysis candidates.")

        return stocks
