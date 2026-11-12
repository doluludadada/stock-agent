from time import perf_counter

from a_domain.ports.market.daily_bar_matrix_provider import IDailyBarMatrixProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.trading.ranking import RankingHistory
from a_domain.types.errors import RankingUnavailable


class RankingHistoryLoader:
    """
    Loads what the monthly ranking reads: every stock's daily history the site holds as listed, delisted stocks too, with
    its total returns, and the monthly revenue the open-data archive holds (IDailyBarMatrixProvider.load_ranking_history),
    which is read from the database only when the site holds other bars, references or revenue than at the load before.
    It fetches nothing. RankingUnavailable while the history holds no session.
    """

    def __init__(self, matrix_provider: IDailyBarMatrixProvider, logger: ILoggingProvider) -> None:
        self._matrix_provider = matrix_provider
        self._logger = logger

    async def execute(self) -> RankingHistory:
        started = perf_counter()
        history = await self._matrix_provider.load_ranking_history()

        if history is None:
            raise RankingUnavailable("No ranking can be made yet: the daily history holds no session.")

        self._logger.info(
            f"Ranking history: {len(history.bars.stock_ids)} stocks x {len(history.bars.sessions)} sessions, {len(history.months)} "
            f"months of revenue, {perf_counter() - started:.1f}s"
        )

        return history
