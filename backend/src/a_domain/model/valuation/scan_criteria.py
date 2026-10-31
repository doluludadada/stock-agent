from __future__ import annotations

import math
from dataclasses import dataclass

from a_domain.model.valuation.target_pe import TargetPe

MIN_UNDERVALUATION_REQUIREMENT = "The minimum undervaluation must be a finite number greater than or equal to 0"


@dataclass(frozen=True)
class ScanCriteria:
    target_pe: TargetPe
    min_undervaluation: float
    """A ratio: 0.3 keeps stocks priced at least 30% below the base fair price."""

    def __post_init__(self) -> None:
        if not math.isfinite(self.min_undervaluation) or self.min_undervaluation < 0:
            raise ValueError(MIN_UNDERVALUATION_REQUIREMENT)
