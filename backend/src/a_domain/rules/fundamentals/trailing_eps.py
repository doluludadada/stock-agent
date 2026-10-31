from dataclasses import dataclass
from datetime import date

from a_domain.model.fundamentals.eps import Eps
from a_domain.model.fundamentals.eps_unavailable import EpsUnavailable
from a_domain.model.fundamentals.fiscal_quarter import FiscalQuarter
from a_domain.model.fundamentals.quarter_eps import EpsFilings, QuarterEps
from a_domain.types.enums import EpsBasis, EpsKind, EpsUnavailableReason, InformationSource


@dataclass(frozen=True)
class TrailingEpsRule:
    """
    Picks the latest candidate quarter a stock has filed and turns cumulative EPS into trailing-twelve-month EPS.

    TTM(Y, n) = cum(Y, n) + cum(Y-1, 4) - cum(Y-1, n) for n < 4, and TTM(Y, 4) = cum(Y, 4).
    Any missing input makes the EPS unavailable with a reason, never 0.
    """

    def apply(self, stock_id: str, filings: EpsFilings, today: date) -> Eps | EpsUnavailable:
        candidates = FiscalQuarter.filing_candidates(today)
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
        prior_year = filing.quarter.ttm_inputs[1:]

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
