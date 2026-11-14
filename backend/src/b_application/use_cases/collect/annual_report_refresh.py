from collections.abc import Sequence
from dataclasses import replace

from a_domain.model.market.company_profile import CompanyProfile
from a_domain.ports.market.annual_report_provider import IAnnualReportProvider
from a_domain.ports.market.article_store import IArticleStore
from a_domain.ports.market.company_profile_repository import ICompanyProfileRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from b_application.config.app_config import AppConfig


class AnnualReportRefresh:
    """
    Brings the annual-report sections of the given companies up to date from the exchange's document site, in the
    order given. A company is looked up when the newest report due is not the one the site read and it has not looked
    within sources.annual_reports.retry_days (AnnualReportDueRule): yearly from June, then weekly until the new report
    appears. A company the site holds no report of also gets the year before's while the newest is not listed yet. A
    report's sections are kept in the article store under the page that lists it, and the company's profile names the
    report's year and file and when the site looked, at once, so a run that stops reads only the rest when it runs
    again. A report with no text to read is named too, with no section: the company simply has none until next
    year's. A company with no report listed, or with one the site could not read, is only marked as looked for, so
    one file that cannot be read never holds up the companies after it. It stops at the first report the site does
    not answer for, since a refused connection means the site asked too much. It answers how many reports it read and
    how many companies it left due. `reports` is None on a site that reads no annual report (public), which reads
    nothing and leaves nothing due.
    """

    def __init__(
        self,
        reports: IAnnualReportProvider | None,
        profiles: ICompanyProfileRepository,
        store: IArticleStore,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._reports = reports
        self._profiles = profiles
        self._store = store
        self._market_clock = market_clock
        self._logger = logger
        self._due_rule = config.sources.annual_reports.due_rule()

    async def execute(self, stock_ids: Sequence[str]) -> tuple[int, int]:
        if self._reports is None:
            return 0, 0

        due: list[tuple[CompanyProfile, int]] = []

        for stock_id in dict.fromkeys(stock_ids):
            profile = await self._profiles.find(stock_id) or CompanyProfile(stock_id=stock_id)
            fiscal_year = self._due_rule.apply(profile, self._market_clock.now())

            if fiscal_year is not None:
                due.append((profile, fiscal_year))

        read, looked = 0, 0

        for profile, fiscal_year in due:
            report = await self._reports.fetch(profile.stock_id, fiscal_year)

            if report is not None and report.file is None and profile.annual_report_year is None:
                report = await self._reports.fetch(profile.stock_id, fiscal_year - 1)

            if report is None:
                self._logger.warning(
                    f"Annual reports: the document site did not answer for {profile.stock_id}; {len(due) - looked} companies left due."
                )
                break

            held = await self._profiles.find(profile.stock_id) or profile
            looked_at = replace(held, annual_report_checked_at=self._market_clock.now())

            if report.file is not None and report.readable:
                await self._store.save(report.sections)
                looked_at = replace(looked_at, annual_report_year=report.fiscal_year, annual_report_file=report.file)
                read += 1

            await self._profiles.save(looked_at)
            looked += 1

        if due:
            self._logger.info(f"Annual reports: looked for {looked} of {len(due)} companies due and read {read} reports.")

        return read, len(due) - looked
