from a_domain.model.trading.backtest import Backtest
from a_domain.ports.trading.backtest_repository import IBacktestRepository
from a_domain.types.ids import BacktestId


class SavedBacktests:
    """
    The user's saved backtests: all of them, newest first, or with `backtest_id` the list that holds that one, empty
    when the user has none of that id.
    """

    def __init__(self, backtest_repository: IBacktestRepository) -> None:
        self._backtest_repository = backtest_repository

    async def execute(self, backtest_id: BacktestId | None = None) -> list[Backtest]:
        if backtest_id is None:
            return await self._backtest_repository.saved()

        found = await self._backtest_repository.get(backtest_id)

        return [] if found is None else [found]
