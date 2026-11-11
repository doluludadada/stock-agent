from collections.abc import Sequence
from datetime import date
from typing import Protocol

from a_domain.rules.technical.matrix import DailyBarMatrix
from a_domain.rules.technical.search import SpanResult, StrategyCandidate


class ICandidateBacktester(Protocol):
    """
    Backtests many candidates of a strategy search over one span of the daily history at once. Each result is what a
    backtest of the candidate's strategy and scores from `first` to `last` comes to (Pipeline.run_backtest), at the
    live trading settings and the mock account's opening cash: the bars from the span's first history window to `last`
    scored as a run would score them (BacktestHistoryRule, StrategyScoresRule) and replayed (BacktestRule). It reads no
    session after `last`, places no order and asks no exchange, broker or AI.
    """

    async def backtest(
        self, bars: DailyBarMatrix, candidates: Sequence[StrategyCandidate], first: date, last: date
    ) -> list[SpanResult]:
        """One result per candidate, in the candidates' order. Candidates of one strategy are scored once."""
        ...
