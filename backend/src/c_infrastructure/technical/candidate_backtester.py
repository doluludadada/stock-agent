import asyncio
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from multiprocessing import get_context
from typing import override

from pydantic import TypeAdapter

from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.candidate_backtester import ICandidateBacktester
from a_domain.rules.technical.matrix import DailyBarMatrix
from a_domain.rules.technical.search import CandidateBacktestRule, SpanResult, StrategyCandidate
from a_domain.rules.technical.strategy import TechnicalStrategy
from a_domain.rules.trading.backtest import BacktestHistoryRule, BacktestPeriodRule
from b_application.config.app_config import AppConfig


class ProcessPoolCandidateBacktester(ICandidateBacktester):
    """
    Backtests candidates in `workers` processes, started at the first call. The candidates of one strategy are one task
    (CandidateBacktestRule), which scores the strategy once and replays it at each candidate's two scores; the task
    carries the bars of its span's history, which its process copies in and drops after. 0 workers runs the tasks in
    this process's worker threads, for the tests and a machine of one core.
    """

    def __init__(self, config: AppConfig, market_clock: IMarketClock, workers: int) -> None:
        self._config = config
        self._session_close = market_clock.session_close
        self._workers = workers
        self._pool: ProcessPoolExecutor | None = None
        self._history_rule = BacktestHistoryRule(period_rule=BacktestPeriodRule())
        self._rule = CandidateBacktestRule(
            initial_cash=config.mock_trading.initial_cash,
            stop_loss_pct=config.analysis.stop_loss_pct,
            risk_per_trade_pct=config.analysis.risk_per_trade_pct,
        )
        self._strategy_json = TypeAdapter(TechnicalStrategy)

    @override
    async def backtest(
        self, bars: DailyBarMatrix, candidates: Sequence[StrategyCandidate], first: date, last: date
    ) -> list[SpanResult]:
        groups: dict[bytes, list[StrategyCandidate]] = {}
        runs: list[asyncio.Future[list[SpanResult]]] = []

        for candidate in candidates:
            groups.setdefault(self._strategy_json.dump_json(candidate.strategy), []).append(candidate)

        if self._pool is None and self._workers:
            self._pool = ProcessPoolExecutor(self._workers, mp_context=get_context("spawn"))

        for group in groups.values():
            history_days = self._config.analysis.history_days(group[0].strategy.required_bars)
            history, window_starts = self._history_rule.apply(bars, first, last, history_days)
            rules = {(each.buy_score, each.sell_score): self._config.backtest_rule(each.buy_score, each.sell_score) for each in group}
            task = (self._rule.apply, history, window_starts, group, first, rules, self._session_close)
            runs.append(asyncio.get_running_loop().run_in_executor(self._pool, *task))

        done = await asyncio.gather(*runs)
        results = {
            each.key: result
            for group, found in zip(groups.values(), done, strict=True)
            for each, result in zip(group, found, strict=True)
        }

        return [results[candidate.key] for candidate in candidates]
