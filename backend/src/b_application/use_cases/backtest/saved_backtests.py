from a_domain.model.trading.backtest import Backtest
from a_domain.ports.trading.backtest_repository import IBacktestRepository


class SavedBacktests:
    """The user's saved backtests, newest first."""

    def __init__(self, backtest_repository: IBacktestRepository) -> None:
        self._backtest_repository = backtest_repository

    async def execute(self) -> list[Backtest]:
        return await self._backtest_repository.saved()
