from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.pipeline_context import PipelineContext


class MarketScanner:
    """Fetches the entire market universe for after-hours full scanning."""

    def __init__(
        self,
        stock_provider: IStockProvider,
        logger: ILoggingProvider,
    ):
        self._stock_provider = stock_provider
        self._logger = logger

    async def execute(self, context: PipelineContext) -> None:
        self._logger.info("Scanning full stock universe...")

        stocks = await self._stock_provider.get_all()

        context.all_stocks = stocks
        context.stats.total_scanned = len(stocks)

        self._logger.info(f"Loaded {len(stocks)} stocks into pipeline.")