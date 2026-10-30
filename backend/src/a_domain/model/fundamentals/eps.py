from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum, auto

from icontract import invariant

from a_domain.types.enums import InformationSource

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


class EpsKind(StrEnum):
    SINGLE_QUARTER = auto()
    CUMULATIVE = auto()
    ANNUAL = auto()
    TRAILING_TWELVE_MONTHS = auto()

    @property
    def label(self) -> str:
        return EPS_KIND_LABELS[self]


EPS_KIND_LABELS = {
    EpsKind.SINGLE_QUARTER: "單季",
    EpsKind.CUMULATIVE: "累計",
    EpsKind.ANNUAL: "年度",
    EpsKind.TRAILING_TWELVE_MONTHS: "近四季 TTM",
}


class EpsBasis(StrEnum):
    ACTUAL = auto()
    ESTIMATE = auto()

    @property
    def label(self) -> str:
        return "實際值" if self == EpsBasis.ACTUAL else "預估值"


class EpsUnavailableReason(StrEnum):
    NOT_LOADED = auto()
    """The workflow did not load fundamentals for this stock."""

    NOT_REPORTED = auto()
    """No filing in any candidate quarter: an ETF, a DR, a new listing or a suspended filer."""

    INCOMPLETE_HISTORY = auto()
    """The TTM needs a prior-year filing the company does not have."""

    SOURCE_FAILED = auto()
    """A quarter the TTM needs could not be fetched."""


@invariant(lambda self: math.isfinite(self.value))
@dataclass(frozen=True)
class Eps:
    """An EPS figure that always carries its period, kind, basis, source and fetch time."""

    value: float
    kind: EpsKind
    period_end: FiscalQuarter
    basis: EpsBasis
    source: InformationSource
    fetched_at: datetime
    """When the period_end quarter was fetched. Older inputs are final filings."""

    newer_quarters: tuple[FiscalQuarter, ...] = ()
    """Newer candidate quarters this figure does not include: not filed yet by the company, or not fetched."""

    @property
    def period_start(self) -> FiscalQuarter:
        if self.kind == EpsKind.SINGLE_QUARTER:
            return self.period_end

        if self.kind == EpsKind.TRAILING_TWELVE_MONTHS:
            return self.period_end.previous().previous().previous()

        return FiscalQuarter(self.period_end.year, 1)

    @property
    def period_label(self) -> str:
        if self.period_start == self.period_end:
            return str(self.period_end)

        return f"{self.period_start}–{self.period_end}"

    def describe(self) -> str:
        """The only text form of an EPS. It never shows the number without its period."""
        return (
            f"{self.value:,.2f} 元（{self.kind.label}，{self.period_label}，{self.basis.label}，"
            f"{SOURCE_LABELS[self.source]}，取得 {self.fetched_at:%Y-%m-%d %H:%M}）"
        )


SOURCE_LABELS = {InformationSource.TWSE_MOPS: "公開資訊觀測站"}


@dataclass(frozen=True)
class EpsUnavailable:
    """Missing EPS. It is never 0, and the report shows 資料不足 with the reason."""

    reason: EpsUnavailableReason
    quarter: FiscalQuarter | None = None

    def describe(self) -> str:
        match self.reason:
            case EpsUnavailableReason.NOT_LOADED:
                return "資料不足：未載入財報資料"
            case EpsUnavailableReason.NOT_REPORTED:
                return f"資料不足：自 {self.quarter} 起無此代號的財報（ETF、DR、新上市或未申報）"
            case EpsUnavailableReason.INCOMPLETE_HISTORY:
                return f"資料不足：缺少 {self.quarter} 累計 EPS，無法計算近四季 EPS"
            case EpsUnavailableReason.SOURCE_FAILED:
                return f"資料不足：{self.quarter} 財報資料取得失敗"


@dataclass(frozen=True)
class QuarterEps:
    """Cumulative year-to-date basic EPS as filed for one quarter, every market merged."""

    quarter: FiscalQuarter
    cumulative_eps: Mapping[str, float]
    fetched_at: datetime
    refresh_failed: bool = False
    """The page was due for a refresh that failed, so it is the last one fetched and may miss later filings."""


type EpsFilings = Mapping[FiscalQuarter, QuarterEps | None]
"""One entry per requested quarter. None means the quarter could not be fetched."""
