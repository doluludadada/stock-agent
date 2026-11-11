from a_domain.model.trading.backtest import Backtest
from a_domain.ports.trading.backtest_repository import IBacktestRepository
from b_application.config.app_config import AppConfig


class BacktestSave:
    """Saves a backtest for its user and keeps the user's newest accounts.saved_backtests, so runs can be compared."""

    def __init__(self, backtest_repository: IBacktestRepository, config: AppConfig) -> None:
        self._backtest_repository = backtest_repository
        self._keep = config.accounts.saved_backtests

    async def execute(self, backtest: Backtest) -> None:
        await self._backtest_repository.save(backtest, self._keep)
