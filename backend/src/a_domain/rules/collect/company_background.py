from datetime import datetime, timedelta
from typing import Annotated

from pydantic import Field, PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.model.market.company_profile import CompanyProfile


@dataclass(frozen=True, kw_only=True)
class MainBusinessDueRule:
    """
    Whether MOPS is asked for a company's basic information now: when the site never asked for it, or last asked
    `max_age_days` or more ago. A company's main business changes rarely, so it is read again once a quarter.
    """

    max_age_days: PositiveInt

    def apply(self, profile: CompanyProfile, now: datetime) -> bool:
        if profile.main_business_fetched_at is None:
            return True

        return now - profile.main_business_fetched_at >= timedelta(days=self.max_age_days)


@dataclass(frozen=True, kw_only=True)
class AnnualReportDueRule:
    """
    Which fiscal year's annual report the site looks for now for a company, or None when it looks for none. Companies
    upload the report of a fiscal year before their shareholders' meeting, by June of the year after, so from
    `first_month` on the newest report is last year's, and before it the year before's. A company whose report of that
    year the site read is not looked for again until next year's is due. Any other is looked for when the site never
    looked, and again `retry_days` after it last did, until the report appears.
    """

    first_month: Annotated[int, Field(ge=1, le=12)]
    retry_days: PositiveInt

    def apply(self, profile: CompanyProfile, now: datetime) -> int | None:
        newest = now.year - 1 if now.month >= self.first_month else now.year - 2

        if profile.annual_report_year is not None and profile.annual_report_year >= newest:
            return None

        if profile.annual_report_checked_at is not None and now - profile.annual_report_checked_at < timedelta(days=self.retry_days):
            return None

        return newest
