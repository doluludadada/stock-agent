from datetime import date

from a_domain.ports.market.daily_close_archive import IDailyCloseArchive, OpenDataDownload
from a_domain.ports.market.fundamentals_provider import IFundamentalsProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.fundamentals.filing import RevenueMonthsRule
from b_application.config.app_config import AppConfig


class RevenueHistoryBackfill:
    """
    Reads every market's monthly revenue from the month `first` falls in to last month out of MOPS's summary of each
    month into the open-data archive, skipping the months the archive already holds as filed in full
    (RevenueMonthsRule). Each month is saved as it is read, so a rerun after a failure reads only what is still due. It
    stops at the first month MOPS does not serve, and answers how many months it read of how many were due; a month the
    archive could not save ends it with ArchiveSaveRefused, counted nowhere. `mops` is
    None on a site that reads no MOPS (public), which reads nothing and answers None.
    """

    def __init__(
        self,
        mops: IFundamentalsProvider | None,
        archive: IDailyCloseArchive,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._mops = mops
        self._archive = archive
        self._market_clock = market_clock
        self._months_rule = RevenueMonthsRule(deadline_day=config.sources.mops.revenue_deadline_day)
        self._logger = logger

    async def execute(self, first: date) -> tuple[int, int] | None:
        if self._mops is None:
            return None

        due = self._months_rule.apply(first, self._market_clock.today(), await self._archive.revenue_served())

        for read, (market, year, month) in enumerate(due):
            revenues = await self._mops.fetch_monthly_revenues(market, year, month)

            if revenues is None:
                self._logger.warning(f"Revenue backfill stopped at {year}-{month:02d} {market.value}: {read}/{len(due)} months read")
                return read, len(due)

            await self._archive.save(
                OpenDataDownload(
                    stocks=[],
                    indexes={},
                    material_information=[],
                    quarter_eps={},
                    valuation_ratios=[],
                    financial_reports=[],
                    monthly_revenues=revenues,
                    exchange_news=[],
                )
            )

        self._logger.info(f"Revenue backfill from {first:%Y-%m}: {len(due)} months read")
        return len(due), len(due)
