from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from a_domain.model.fundamentals.fiscal_quarter import FiscalQuarter


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
