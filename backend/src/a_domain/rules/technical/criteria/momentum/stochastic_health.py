# backend/src/a_domain/rules/technical/criteria/momentum/stochastic_health.py

from dataclasses import dataclass

import icontract

from a_domain.model.market.stock import Stock


@icontract.invariant(lambda self: self.max_k is None or 0 <= self.max_k <= 100)
@dataclass(frozen=True)
class StochasticHealthCriterion:
    """Checks the current stochastic oscillator state."""

    max_k: float | None = 80.0
    require_k_above_d: bool = False

    @property
    def name(self) -> str:
        checks: list[str] = []

        if self.max_k is not None:
            checks.append(f"K < {self.max_k}")

        if self.require_k_above_d:
            checks.append("K > D")

        if not checks:
            return "Stochastic Available"

        return f"Stochastic Health ({', '.join(checks)})"

    def apply(self, stock: Stock) -> bool:
        stochastic = stock.indicators.stochastic

        if stochastic is None:
            return False

        if self.max_k is not None and stochastic.k >= self.max_k:
            return False

        return not self.require_k_above_d or stochastic.k > stochastic.d
