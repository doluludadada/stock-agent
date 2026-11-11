import asyncio
from time import perf_counter

from a_domain.model.trading.backtest import BacktestInputs
from a_domain.ports.market.daily_bar_matrix_provider import IDailyBarMatrixProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.technical.matrix import DailyBarMatrix, StrategyScores, StrategyScoresRule
from a_domain.rules.technical.strategy import TechnicalStrategy
from a_domain.rules.trading.backtest import BacktestHistoryRule, BacktestPeriodRule
from a_domain.types.errors import BacktestPeriodUnavailable
from b_application.config.app_config import AppConfig


class BacktestScores:
    """
    Scores every listed stock on every session a backtest of `inputs` reads, and returns those bars with the scores:
    the held daily history from the first session's history window on (BacktestHistoryRule), and the strategy's score
    and verdict of each stock on each session over the window a run would read that day (StrategyScoresRule). It
    fetches no session the history lacks: a period outside the held sessions raises BacktestPeriodUnavailable, which
    says what may be covered.

    The scores are seconds of computation, so they run in a worker thread and the Web API keeps answering meanwhile.
    """

    def __init__(self, matrix_provider: IDailyBarMatrixProvider, config: AppConfig, logger: ILoggingProvider) -> None:
        self._matrix_provider = matrix_provider
        self._history_days = config.analysis.history_days
        self._history_rule = BacktestHistoryRule(period_rule=BacktestPeriodRule())
        self._logger = logger

    async def execute(self, strategy: TechnicalStrategy, inputs: BacktestInputs) -> tuple[DailyBarMatrix, StrategyScores]:
        started = perf_counter()
        bars = await self._matrix_provider.load()

        if bars is None:
            raise BacktestPeriodUnavailable("No backtest can run yet: the daily history holds no session.")

        history_days = self._history_days(strategy.required_bars)
        history, window_starts = self._history_rule.apply(bars, inputs.first, inputs.last, history_days)
        loaded = perf_counter()
        scores = await asyncio.to_thread(StrategyScoresRule(strategy=strategy).apply, history, window_starts)
        self._logger.info(
            f"Backtest scores of {strategy.strategy_id}: {len(history.stock_ids)} stocks x {len(history.sessions)} sessions; "
            f"history {loaded - started:.2f}s, scores {perf_counter() - loaded:.2f}s"
        )

        return history, scores
