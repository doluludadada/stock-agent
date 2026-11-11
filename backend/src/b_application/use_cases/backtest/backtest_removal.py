from a_domain.ports.trading.backtest_repository import IBacktestRepository
from a_domain.types.ids import BacktestId


class BacktestRemoval:
    """Deletes one of the user's saved backtests. It answers whether the user had one of that id."""

    def __init__(self, backtest_repository: IBacktestRepository) -> None:
        self._backtest_repository = backtest_repository

    async def execute(self, backtest_id: BacktestId) -> bool:
        return await self._backtest_repository.delete(backtest_id)
