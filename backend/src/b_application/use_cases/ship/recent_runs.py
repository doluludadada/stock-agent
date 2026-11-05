from a_domain.model.system.stats import SystemStats
from a_domain.ports.trading.trading_journal import ITradingJournal


class RecentRuns:
    """The recorded runs, newest first, whichever entry point started them: the runs page reads them a page at a time."""

    def __init__(self, journal: ITradingJournal) -> None:
        self._journal = journal

    async def execute(self, limit: int, offset: int) -> list[SystemStats]:
        return await self._journal.recent_runs(limit, offset)
