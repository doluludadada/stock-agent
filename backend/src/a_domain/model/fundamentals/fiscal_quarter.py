from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from icontract import invariant

# The latest statutory deadline per quarter across company types (financial holdings file last).
# The Q4 (annual) report is due in the following year.
FILING_DEADLINE: dict[int, tuple[int, int]] = {1: (5, 30), 2: (8, 31), 3: (11, 29), 4: (3, 31)}


# A deadline that falls on a holiday moves to the next business day, so filings can still arrive for a few days.
FILING_GRACE = timedelta(days=7)


@invariant(lambda self: 1 <= self.quarter <= 4)
@dataclass(frozen=True, order=True)
class FiscalQuarter:
    """A calendar-year fiscal quarter in Gregorian years. The MOPS adapter converts ROC years."""

    year: int
    quarter: int

    @classmethod
    def latest_ended(cls, day: date) -> FiscalQuarter:
        """The last quarter that ended before `day`: 2026-10-30 is 2026Q3, 2026-10-01 is 2026Q3, 2026-09-30 is 2026Q2."""
        return cls(day.year, (day.month - 1) // 3 + 1).previous()

    def previous(self) -> FiscalQuarter:
        if self.quarter == 1:
            return FiscalQuarter(self.year - 1, 4)

        return FiscalQuarter(self.year, self.quarter - 1)

    @property
    def filing_deadline(self) -> date:
        month, day = FILING_DEADLINE[self.quarter]
        year = self.year + 1 if self.quarter == 4 else self.year

        return date(year, month, day)

    def is_final_on(self, day: date) -> bool:
        """True once every company type's deadline plus the grace has passed, so the filings no longer change."""
        return day > self.filing_deadline + FILING_GRACE

    @property
    def ttm_inputs(self) -> tuple[FiscalQuarter, ...]:
        """Cumulative reports a TTM ending here needs: Q4 is the annual report; otherwise (Y,n), (Y-1,4), (Y-1,n)."""
        if self.quarter == 4:
            return (self,)

        return (self, FiscalQuarter(self.year - 1, 4), FiscalQuarter(self.year - 1, self.quarter))

    def __str__(self) -> str:
        return f"{self.year}Q{self.quarter}"
