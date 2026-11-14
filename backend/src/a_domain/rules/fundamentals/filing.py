from collections.abc import Mapping
from datetime import date, timedelta
from typing import Annotated

from pydantic import Field, NonNegativeInt
from pydantic.dataclasses import dataclass

from a_domain.rules.fundamentals.trailing_eps import EpsFilings
from a_domain.types.enums import MarketType
from a_domain.types.values import FiscalQuarter, month_index, month_start


@dataclass(frozen=True)
class FilingDeadlineRule:
    """A quarter's latest statutory filing deadline across company types. The Q4 (annual) report is due the next year."""

    deadlines: Mapping[int, tuple[int, int]]
    """(month, day) per quarter number."""

    def apply(self, quarter: FiscalQuarter) -> date:
        month, day = self.deadlines[quarter.quarter]
        year = quarter.year + 1 if quarter.quarter == 4 else quarter.year

        return date(year, month, day)


@dataclass(frozen=True)
class FinalFilingsRule:
    """
    True once the quarter's deadline plus `grace_days` has passed on `day`, so its filings no longer change.
    The grace covers a deadline on a holiday, which moves to the next business day.
    """

    filing_deadline_rule: FilingDeadlineRule
    grace_days: NonNegativeInt

    def apply(self, quarter: FiscalQuarter, day: date) -> bool:
        return day > self.filing_deadline_rule.apply(quarter) + timedelta(days=self.grace_days)


@dataclass(frozen=True)
class FilingWarningRule:
    """One warning per quarter whose filings could not be fetched or whose refresh failed, oldest quarter first."""

    def apply(self, filings: EpsFilings) -> tuple[str, ...]:
        warnings: list[str] = []

        for quarter in sorted(filings):
            filing = filings[quarter]

            if filing is None:
                warnings.append(
                    f"MOPS {quarter} filings could not be fetched; the EPS of a stock that needs this quarter shows insufficient data "
                    "or comes from an older quarter"
                )
                continue

            if filing.refresh_failed:
                warnings.append(
                    f"MOPS {quarter} filings could not be refreshed, so the data fetched at {filing.fetched_at:%Y-%m-%d %H:%M} "
                    "is used; the EPS of a company that filed after that shows insufficient data or comes from an older quarter"
                )

        return tuple(warnings)


@dataclass(frozen=True)
class RevenueMonthsRule:
    """
    The months of revenue a backfill from `first` reads, oldest first, each with its market: every market's months from
    the one `first` falls in to the one before `today`'s, but those `served` holds as served after the deadline, the
    `deadline_day` of the month after them, by when every company had filed. `served` is the latest day the archive's
    revenue of each market's month was served, so a month read before its deadline is read again.
    """

    deadline_day: Annotated[int, Field(ge=1, le=28)]

    def apply(self, first: date, today: date, served: Mapping[tuple[MarketType, int, int], date]) -> list[tuple[MarketType, int, int]]:
        months = range(month_index(first.year, first.month), month_index(today.year, today.month))
        due: list[tuple[MarketType, int, int]] = []

        for index in months:
            year, month = divmod(index, 12)
            deadline = month_start(index + 1).replace(day=self.deadline_day)
            due += [
                (market, year, month + 1) for market in MarketType if not served.get((market, year, month + 1), deadline) > deadline
            ]

        return due
