from datetime import date

from a_domain.ports.market.daily_close_archive import IDailyCloseArchive, OpenDataDownload
from a_domain.ports.market.fundamentals_provider import IFundamentalsProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.fundamentals.filing import RevenueMonthsRule
from a_domain.rules.fundamentals.trailing_eps import filing_candidates
from a_domain.types.values import FiscalQuarter
from b_application.config.app_config import AppConfig


class FundamentalsHistoryBackfill:
    """
    Reads from MOPS what the companies filed since `first`, and answers two counts.

    Monthly revenue: every market's revenue from the month `first` falls in to last month out of MOPS's summary of
    each month into the open-data archive, skipping the months the archive already holds as filed in full
    (RevenueMonthsRule). Each month is saved as it is read, so a rerun after a failure reads only what is still due.
    It stops at the first month MOPS does not serve, and answers how many months it read of how many were due; a month
    the archive could not save ends the step with ArchiveSaveRefused, counted nowhere.

    Year-to-date EPS: every market's MOPS page for each quarter from the one `first` falls in to the latest that may
    be filed, into the pages the site holds (IFundamentalsProvider.fetch_cumulative_eps), which the stock page's
    earnings trend reads. A page already held as final is not fetched again, so a rerun reads only what is missing. It
    answers how many quarters it holds of how many were due.

    `mops` is None on a site that reads no MOPS (public), which reads nothing and answers None for both.
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

    async def execute(self, first: date) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
        if self._mops is None:
            return None, None

        months = self._months_rule.apply(first, self._market_clock.today(), await self._archive.revenue_served())
        read = 0

        for market, year, month in months:
            revenues = await self._mops.fetch_monthly_revenues(market, year, month)

            if revenues is None:
                self._logger.warning(
                    f"Revenue backfill stopped at {year}-{month:02d} {market.value}: {read}/{len(months)} months read"
                )
                break

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
            read += 1
        else:
            self._logger.info(f"Revenue backfill from {first:%Y-%m}: {len(months)} months read")

        oldest = FiscalQuarter(first.year, (first.month - 1) // 3 + 1)
        quarters = [filing_candidates(self._market_clock.today())[0]]

        while quarters[-1] > oldest:
            quarters.append(quarters[-1].previous())

        filings = await self._mops.fetch_cumulative_eps([quarter for quarter in quarters if quarter >= oldest])
        held = sum(filing is not None for filing in filings.values())
        self._logger.info(f"EPS backfill from {oldest}: {held}/{len(filings)} quarters held")

        return (read, len(months)), (held, len(filings))
