from a_domain.model.trading.account import Account
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from b_application.schemas.pipeline_context import PipelineContext


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
    ):
        self._execution_provider = execution_provider
        self._stock_provider = stock_provider
        self._logger = logger

    async def execute(self, context: PipelineContext) -> None:
        cash = await self._execution_provider.get_cash_balance()
        positions = await self._execution_provider.get_positions()

        context.account = Account(
            cash=cash,
            positions=positions,
        )

        context.positions_by_stock_id = {position.stock_id: position for position in positions}

        context.held_stocks.clear()

        for position in positions:
            stock = await self._stock_provider.get_by_id(position.stock_id)

            if stock is None:
                self._logger.warning(f"Held stock not found: {position.stock_id}")
                continue

            context.held_stocks.append(stock)

        self._logger.info(
            f"Account loaded. Cash={cash}, Positions={len(positions)}, HeldCandidates={len(context.held_stocks)}"
        )
