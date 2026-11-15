from datetime import date
from time import perf_counter

from a_domain.ports.market.daily_bar_matrix_provider import IDailyBarMatrixProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.trading.ranking import RankingHistory
from a_domain.rules.trading.ranking_backtest import RankingBacktest
from a_domain.types.values import FormulaId
from b_application.config.app_config import AppConfig


class RankingReplay:
    """
    Replays the monthly ranking from `first` to `last` on the history (RankingBacktestRule) by the formula named, the
    active one when none is, each ranked stock with its name in the exchange listing, at the live fee and tax. It reads
    no account, asks no AI and places no order. UnknownRankingFormula for a name the settings lack, and
    BacktestPeriodUnavailable for a period without a decision session.

    The replay is computation alone: the matrix provider works it out in a worker thread, so the Web API keeps
    answering meanwhile, and keeps it while the history it read stands.
    """

    def __init__(
        self, matrix_provider: IDailyBarMatrixProvider, stock_provider: IStockProvider, config: AppConfig, logger: ILoggingProvider
    ) -> None:
        self._matrix_provider = matrix_provider
        self._stock_provider = stock_provider
        self._formula = config.ranking.formula
        self._replay_rule = config.ranking_backtest_rule
        self._logger = logger

    async def execute(
        self, history: RankingHistory, first: date, last: date, formula_name: FormulaId | None = None
    ) -> RankingBacktest:
        started = perf_counter()
        rule = self._replay_rule(self._formula(formula_name))
        names = {stock.stock_id: stock.name for stock in await self._stock_provider.get_all()}
        backtest = await self._matrix_provider.ranking_backtest(history, rule, names, first, last)
        self._logger.info(
            f"Ranking backtest of {backtest.formula.name} from {first} to {last}: {len(backtest.equity_curve)} sessions, "
            f"{len(backtest.rankings)} decisions, {perf_counter() - started:.1f}s"
        )

        return backtest
