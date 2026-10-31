from a_domain.model.market.stock import Stock
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.pipeline_status import PipelineStatus


class StockLookup:
    """
    Loads explicitly requested stock IDs for specific-stock analysis: each ID once, in the order asked.

    A stock this run already loaded is reused. An unknown ID is a run error, not an exception.
    """

    def __init__(self, stock_provider: IStockProvider, logger: ILoggingProvider) -> None:
        self._stock_provider = stock_provider
        self._logger = logger

    async def execute(self, stock_ids: list[str], status: PipelineStatus) -> list[Stock]:
        stocks: list[Stock] = []

        for stock_id in dict.fromkeys(stock_id.strip() for stock_id in stock_ids if stock_id.strip()):
            stock = status.stocks_cache.get(stock_id) or await self._stock_provider.get_by_id(stock_id)

            if stock is None:
                self._logger.warning(f"Stock not found: {stock_id}")
                status.stats.add_error(f"Stock not found: {stock_id}")
                continue

            status.stocks_cache[stock.stock_id] = stock
            stocks.append(stock)

        return stocks
