from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from b_application.schemas.pipeline_status import PipelineStatus


class AccountLoader:
    """
    Use Case: Load the broker account into the run, and each held stock as analysis context.

    Position only stores broker/account ownership state. Stock is loaded separately as pipeline
    analysis context, from the run's cache when an earlier step already loaded it.
    """

    def __init__(self, execution_provider: IExecutionProvider, stock_provider: IStockProvider, logger: ILoggingProvider) -> None:
        self._execution_provider = execution_provider
        self._stock_provider = stock_provider
        self._logger = logger

    async def execute(self, status: PipelineStatus) -> None:
        status.account = await self._execution_provider.get_account()
        status.held_stocks.clear()

        for position in status.account.positions:
            stock = status.stocks_cache.get(position.stock_id)

            if stock is None:
                stock = await self._stock_provider.get_by_id(position.stock_id)

            if stock is None:
                self._logger.warning(f"Held stock not found: {position.stock_id}")
                continue

            status.stocks_cache[stock.stock_id] = stock
            status.held_stocks.append(stock)

        account = status.account
        self._logger.info(
            f"Account loaded. Cash={account.cash}, Positions={len(account.positions)}, HeldCandidates={len(status.held_stocks)}"
        )
