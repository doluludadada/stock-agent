from typing import Protocol

from a_domain.rules.technical.matrix import DailyBarMatrix
from a_domain.rules.trading.ranking import RankingHistory


class IDailyBarMatrixProvider(Protocol):
    """
    Every listed stock's adjusted daily history over the sessions the price source already holds (held_span), as one
    matrix: the history a run's analysis reads, for a backtest of the whole market; and what the monthly ranking reads,
    every stock's history as listed, delisted stocks too, with the archived monthly revenue. Building either reads every
    bar, which takes seconds, so the adapter keeps each in memory. It never fetches a session the source lacks.
    """

    async def load(self) -> DailyBarMatrix | None:
        """
        The matrix, or None while the source holds no session; built again only when the source holds another span of
        sessions. Its arrays are shared: a caller never writes them.
        """
        ...

    async def load_ranking_history(self) -> RankingHistory | None:
        """
        Every stock's bars the source holds as listed with their total returns and the archived revenue
        (ListedHistoryRule, RankingHistoryRule), or None while the source holds no bar. It is built again whenever the
        source's bars, its ex-right references or the archived revenue changed (listed_fingerprint,
        revenue_fingerprint), so it is never older than they are. Its arrays are shared: a caller never writes them.
        """
        ...
