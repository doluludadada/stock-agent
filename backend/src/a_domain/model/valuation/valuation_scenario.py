from __future__ import annotations

import math
from dataclasses import dataclass

from icontract import invariant

from a_domain.model.valuation.pe_ratio import PeRatio
from a_domain.types.enums import ScenarioName


@invariant(lambda self: math.isfinite(self.target_pe) and self.target_pe > 0)
@dataclass(frozen=True)
class ValuationScenario:
    name: ScenarioName
    target_pe: float
    assumption: str
    pe: PeRatio

    @property
    def fair_price(self) -> float:
        return self.pe.eps * self.target_pe

    @property
    def gap(self) -> float:
        return self.fair_price - self.pe.price

    @property
    def undervaluation(self) -> float:
        """(fair price − price) ÷ price. Positive is undervalued, negative is overvalued."""
        return self.gap / self.pe.price
