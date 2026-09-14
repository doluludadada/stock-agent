from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from b_application.schemas.pipeline_status import PipelineStatus


class AccountLoader:
    """
    Use Case: Load account state and enrich held position candidates.

    Position only stores broker/account ownership state.
    Stock is loaded separately as pipeline analysis context.
    """

    def __init__(
        self,
        execution_provider: IExecutionProvider,
        stock_provider: IStockProvider,
        logger: ILoggingProvider,
    ) -> None:
        self._execution_provider = execution_provider
        self._stock_provider = stock_provider
        self._logger = logger

    async def execute(
        self,
        status: PipelineStatus,
    ) -> None:
        cash = await self._execution_provider.get_cash_balance()
        positions = await self._execution_provider.get_positions()

        status.account = Account(
            cash=cash,
            positions=positions,
        )
        status.positions_by_stock_id = {
            position.stock_id: position
            for position in positions
        }
        status.held_stocks.clear()

        for position in positions:
            stock = await self.load_stock(
                position.stock_id,
                status,
            )

            if stock is not None:
                status.held_stocks.append(stock)

        self._logger.info(
            f"Account loaded. Cash={cash}, "
            f"Positions={len(positions)}, "
            f"HeldCandidates={len(status.held_stocks)}"
        )

    async def load_stock(
        self,
        stock_id: str,
        status: PipelineStatus,
    ) -> Stock | None:
        cached_stock = status.stocks_cache.get(stock_id)

        if cached_stock is not None:
            return cached_stock

        source_stock = await self._stock_provider.get_by_id(stock_id)

        if source_stock is None:
            self._logger.warning(
                f"Held stock not found: {stock_id}"
            )
            return None

        stock = source_stock.model_copy(deep=True)
        stock.realtime_bar = None
        status.stocks_cache[stock.stock_id] = stock

        return stock
