from a_domain.model.market.stock import Stock
from a_domain.model.trading.account_snapshot import AccountSnapshot
from a_domain.model.trading.order import Order
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from b_application.schemas.pipeline_status import PipelineStatus


class AccountLoader:
    """
    Use Case: Load the broker account into the run, and snapshot it after every fill.

    Position only stores broker/account ownership state.
    Stock is loaded separately as pipeline analysis context.
    """

    def __init__(
        self,
        execution_provider: IExecutionProvider,
        stock_provider: IStockProvider,
        journal: ITradingJournal,
        market_clock: IMarketClock,
        logger: ILoggingProvider,
    ) -> None:
        self._execution_provider = execution_provider
        self._stock_provider = stock_provider
        self._journal = journal
        self._market_clock = market_clock
        self._logger = logger

    async def execute(self, status: PipelineStatus) -> None:
        status.account = await self._execution_provider.get_account()
        status.held_stocks.clear()

        for position in status.account.positions:
            stock = await self.load_stock(position.stock_id, status)

            if stock is not None:
                status.held_stocks.append(stock)

        account = status.account
        self._logger.info(
            f"Account loaded. Cash={account.cash}, Positions={len(account.positions)}, HeldCandidates={len(status.held_stocks)}"
        )

    async def record_fill(self, status: PipelineStatus, order: Order) -> None:
        """Re-reads the account after `order` filled and saves the snapshot."""
        status.account = await self._execution_provider.get_account()
        latest_prices = {stock_id: stock.current_price for stock_id, stock in status.stocks_cache.items() if stock.current_price}
        snapshot = AccountSnapshot.after_fill(order, status.account, latest_prices, taken_at=self._market_clock.now())

        await self._journal.save_snapshot(snapshot)

    async def load_stock(self, stock_id: str, status: PipelineStatus) -> Stock | None:
        cached_stock = status.stocks_cache.get(stock_id)

        if cached_stock is not None:
            return cached_stock

        stock = await self._stock_provider.get_by_id(stock_id)

        if stock is None:
            self._logger.warning(f"Held stock not found: {stock_id}")
            return None

        status.stocks_cache[stock.stock_id] = stock

        return stock
