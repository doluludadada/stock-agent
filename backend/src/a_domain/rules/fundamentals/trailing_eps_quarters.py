from dataclasses import dataclass
from datetime import date

from a_domain.model.fundamentals.fiscal_quarter import FiscalQuarter


@dataclass(frozen=True)
class TrailingEpsQuartersRule:
    """The cumulative reports TrailingEpsRule reads on `today`: each candidate quarter's and the prior-year ones it nets against."""

    def apply(self, today: date) -> frozenset[FiscalQuarter]:
        return frozenset(quarter for candidate in FiscalQuarter.filing_candidates(today) for quarter in candidate.ttm_inputs)
