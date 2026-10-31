from __future__ import annotations

from dataclasses import dataclass

from a_domain.model.fundamentals.fiscal_quarter import FiscalQuarter
from a_domain.types.enums import EpsUnavailableReason


@dataclass(frozen=True)
class EpsUnavailable:
    """Missing EPS. It is never 0, and the report shows "Insufficient data" with the reason."""

    reason: EpsUnavailableReason
    quarter: FiscalQuarter | None = None

    def describe(self) -> str:
        match self.reason:
            case EpsUnavailableReason.NOT_LOADED:
                return "Insufficient data: no financial statements were loaded"
            case EpsUnavailableReason.NOT_REPORTED:
                return (
                    f"Insufficient data: no filing for this code since {self.quarter} "
                    "(an ETF, a DR, a new listing or a company that has not filed)"
                )
            case EpsUnavailableReason.INCOMPLETE_HISTORY:
                return f"Insufficient data: the cumulative EPS for {self.quarter} is missing, so the TTM EPS cannot be computed"
            case EpsUnavailableReason.SOURCE_FAILED:
                return f"Insufficient data: the {self.quarter} filings could not be fetched"
