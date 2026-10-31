from __future__ import annotations

import math
from dataclasses import dataclass

from a_domain.model.valuation.target_pe import TargetPe


@dataclass(frozen=True)
class ScanCriteria:
    target_pe: TargetPe
    min_undervaluation: float
    """A ratio: 0.3 keeps stocks priced at least 30% below the base fair price."""

    def __post_init__(self) -> None:
        if not math.isfinite(self.min_undervaluation) or self.min_undervaluation < 0:
            raise ValueError("最低低估幅度必須是大於或等於 0 的有限數字")
