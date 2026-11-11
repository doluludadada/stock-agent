from typing import Protocol

from a_domain.rules.technical.matrix import DailyBarMatrix


class IDailyBarMatrixProvider(Protocol):
    """
    Every listed stock's adjusted daily history over the sessions the price source already holds (held_span), as one
    matrix: the history a run's analysis reads, for a backtest of the whole market. Building it reads and adjusts every
    bar, which takes seconds, so the adapter keeps the matrix in memory and builds it again only when the source holds
    another span of sessions. It never fetches a session the source lacks.
    """

    async def load(self) -> DailyBarMatrix | None:
        """The matrix, or None while the source holds no session. Its arrays are shared: a caller never writes them."""
        ...
