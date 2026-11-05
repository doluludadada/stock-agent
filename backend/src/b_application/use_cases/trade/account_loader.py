from collections.abc import Mapping

from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider


class AccountLoader:
    """
    Use Case: Load the broker account into the run, and each held stock as analysis context.

    Position only stores broker/account ownership state. Stock is loaded separately as pipeline analysis context,
    reusing a stock the run already loaded (manual BUY's analysed stock). It returns the account and one Stock per
    position it found.
    """

    def __init__(self, execution_provider: IExecutionProvider, stock_provider: IStockProvider, logger: ILoggingProvider) -> None:
        self._execution_provider = execution_provider
        self._stock_provider = stock_provider
        self._logger = logger

    async def execute(self, known: Mapping[str, Stock]) -> tuple[Account, list[Stock]]:
        account = await self._execution_provider.get_account()
        held_stocks: list[Stock] = []

        for position in account.positions:
            stock = known.get(position.stock_id)

            if stock is None:
                stock = await self._stock_provider.get_by_id(position.stock_id)

            if stock is None:
                self._logger.warning(f"Held stock not found: {position.stock_id}")
                continue

            held_stocks.append(stock)

        self._logger.info(
            f"Account loaded. Cash={account.cash}, Positions={len(account.positions)}, HeldCandidates={len(held_stocks)}"
        )

        return account, held_stocks
