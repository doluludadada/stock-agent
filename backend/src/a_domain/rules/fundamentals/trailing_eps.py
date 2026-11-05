from collections.abc import Mapping
from datetime import date, datetime

from pydantic.dataclasses import dataclass

from a_domain.model.fundamentals.eps import Eps, EpsUnavailable
from a_domain.types.enums import EpsBasis, EpsKind, EpsUnavailableReason, InformationSource
from a_domain.types.values import FiscalQuarter


@dataclass(frozen=True)
class QuarterEps:
    """Cumulative year-to-date basic EPS as filed for one quarter: one market's MOPS page, or every market merged."""

    quarter: FiscalQuarter
    cumulative_eps: Mapping[str, float]
    fetched_at: datetime
    refresh_failed: bool = False
    """The page was due for a refresh that failed, so it is the last one fetched and may miss later filings."""


type EpsFilings = Mapping[FiscalQuarter, QuarterEps | None]
"""One entry per requested quarter. None means the quarter could not be fetched."""


def filing_candidates(day: date) -> tuple[FiscalQuarter, FiscalQuarter]:
    """
    Newest first: the last quarter that ended before `day`, which may still be being filed, and the one before it.
    On 2026-10-30 and 2026-10-01 they are 2026Q3 and 2026Q2; on 2026-09-30 they are 2026Q2 and 2026Q1.

    Two suffice: each quarter's filing deadline falls on or before the end of the next quarter, so while one
    quarter is being filed, the quarter before it is complete.
    """
    latest = FiscalQuarter(day.year, (day.month - 1) // 3 + 1).previous()
    return (latest, latest.previous())


def ttm_inputs(quarter: FiscalQuarter) -> tuple[FiscalQuarter, ...]:
    """Cumulative reports a TTM ending at `quarter` needs: Q4 is the annual report; otherwise (Y,n), (Y-1,4), (Y-1,n)."""
    if quarter.quarter == 4:
        return (quarter,)

    return (quarter, FiscalQuarter(quarter.year - 1, 4), FiscalQuarter(quarter.year - 1, quarter.quarter))


@dataclass(frozen=True)
class TrailingEpsRule:
    """
    Picks the latest candidate quarter a stock has filed and turns cumulative EPS into trailing-twelve-month EPS.

    TTM(Y, n) = cum(Y, n) + cum(Y-1, 4) - cum(Y-1, n) for n < 4, and TTM(Y, 4) = cum(Y, 4).
    Any missing input makes the EPS unavailable with a reason, never 0.
    """

    def apply(self, stock_id: str, filings: EpsFilings, today: date) -> Eps | EpsUnavailable:
        candidates = filing_candidates(today)
        newer: list[FiscalQuarter] = []

        for candidate in candidates:
            filing = filings.get(candidate)

            if filing is not None and stock_id in filing.cumulative_eps:
                return self._trailing(stock_id, filing, filings, tuple(newer))

            newer.append(candidate)

        oldest = candidates[-1]
        reason = EpsUnavailableReason.SOURCE_FAILED if filings.get(oldest) is None else EpsUnavailableReason.NOT_REPORTED

        return EpsUnavailable(reason=reason, quarter=oldest)

    def _trailing(
        self, stock_id: str, filing: QuarterEps, filings: EpsFilings, newer: tuple[FiscalQuarter, ...]
    ) -> Eps | EpsUnavailable:
        value = filing.cumulative_eps[stock_id]
        prior_year = ttm_inputs(filing.quarter)[1:]

        for needed, sign in zip(prior_year, (1, -1), strict=False):
            prior = filings.get(needed)

            if prior is None:
                return EpsUnavailable(reason=EpsUnavailableReason.SOURCE_FAILED, quarter=needed)

            if stock_id not in prior.cumulative_eps:
                return EpsUnavailable(reason=EpsUnavailableReason.INCOMPLETE_HISTORY, quarter=needed)

            value += sign * prior.cumulative_eps[stock_id]

        # MOPS reports two decimals; rounding keeps a TTM that nets to zero at exactly 0.
        return Eps(
            value=round(value, 2),
            kind=EpsKind.TRAILING_TWELVE_MONTHS,
            period_end=filing.quarter,
            basis=EpsBasis.ACTUAL,
            source=InformationSource.TWSE_MOPS,
            fetched_at=filing.fetched_at,
            newer_quarters=newer,
        )


@dataclass(frozen=True)
class TrailingEpsQuartersRule:
    """The cumulative reports TrailingEpsRule reads on `today`: each candidate quarter's and the prior-year ones it nets against."""

    def apply(self, today: date) -> frozenset[FiscalQuarter]:
        return frozenset(quarter for candidate in filing_candidates(today) for quarter in ttm_inputs(candidate))
