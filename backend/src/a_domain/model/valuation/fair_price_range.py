from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from icontract import require

from a_domain.model.valuation.pe_ratio import PeRatio
from a_domain.model.valuation.target_pe import TargetPe
from a_domain.model.valuation.valuation_scenario import ValuationScenario
from a_domain.types.enums import ScenarioName


@dataclass(frozen=True)
class FairPriceRange:
    """Three scenarios: the user's target P/E, and the configured spread below and above it."""

    conservative: ValuationScenario
    base: ValuationScenario
    optimistic: ValuationScenario

    @classmethod
    @require(lambda spread: 0 < spread < 1)
    def of(cls, pe: PeRatio, target: TargetPe, spread: float) -> FairPriceRange:
        def around_base(name: ScenarioName, factor: float, sign: str) -> ValuationScenario:
            assumption = f"基準 × (1 {sign} {spread:.0%})，依設定 valuation.scenario_spread"
            return ValuationScenario(name=name, target_pe=target.value * factor, assumption=assumption, pe=pe)

        return cls(
            conservative=around_base(ScenarioName.CONSERVATIVE, 1 - spread, "−"),
            base=ValuationScenario(name=ScenarioName.BASE, target_pe=target.value, assumption="使用者輸入的目標本益比", pe=pe),
            optimistic=around_base(ScenarioName.OPTIMISTIC, 1 + spread, "+"),
        )

    def __iter__(self) -> Iterator[ValuationScenario]:
        return iter((self.conservative, self.base, self.optimistic))
