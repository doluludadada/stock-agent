from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.pipeline_status import PipelineStatus


class MarketScanner:
    """Loads the full stock universe into universe_stocks for Full Cycle."""

    def __init__(self, stock_provider: IStockProvider, logger: ILoggingProvider) -> None:
        self._stock_provider = stock_provider
        self._logger = logger

    async def execute(self, status: PipelineStatus) -> None:
        self._logger.info("Scanning full stock universe...")
        stocks = await self._stock_provider.get_all()

        status.universe_stocks = stocks
        status.stats.total_scanned = len(stocks)

        for stock in stocks:
            status.stocks_cache[stock.stock_id] = stock

        self._logger.info(f"Loaded {len(stocks)} universe stocks into analysis candidates.")
