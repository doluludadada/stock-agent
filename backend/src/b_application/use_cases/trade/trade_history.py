from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.order import Order
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal


class TradeHistory:
    """
    Use Case: The account's trades, newest first: every order that filled at least one share since the mock account
    opened (every one at a real broker), each with the run whose decision it carried out. It records no run.
    """

    def __init__(self, execution_provider: IExecutionProvider, journal: ITradingJournal) -> None:
        self._execution_provider = execution_provider
        self._journal = journal

    async def execute(self, limit: int, offset: int) -> list[tuple[Order, SystemStats]]:
        account = await self._execution_provider.get_account()

        return await self._journal.trades(account.opened_at, limit, offset)
