from a_domain.model.trading.backtest import Backtest
from a_domain.ports.trading.backtest_repository import IBacktestRepository
from a_domain.types.ids import BacktestId


class BacktestLookup:
    """One of the user's saved backtests, or None when the user has none of that id."""

    def __init__(self, backtest_repository: IBacktestRepository) -> None:
        self._backtest_repository = backtest_repository

    async def execute(self, backtest_id: BacktestId) -> Backtest | None:
        return await self._backtest_repository.get(backtest_id)
