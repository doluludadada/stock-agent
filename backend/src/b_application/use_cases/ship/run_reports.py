from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.trading_journal import ITradingJournal


class RunReports:
    """
    Saves a specific-stock analysis's reports under its run, so a client reads them after the server restarts. A
    failed save is a run error; the analysis itself stands.
    """

    def __init__(self, journal: ITradingJournal, logger: ILoggingProvider) -> None:
        self._journal = journal
        self._logger = logger

    async def execute(self, stocks: list[Stock], stats: SystemStats) -> None:
        try:
            await self._journal.save_stock_reports(stats.run_id, stocks)
        except Exception as error:
            self._logger.error(stats.add_error(f"Stock reports not saved: {stats.run_id}, error={error}"))
