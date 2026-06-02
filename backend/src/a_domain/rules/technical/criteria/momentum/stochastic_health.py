from dataclasses import dataclass

from a_domain.model.market.stock import Stock


@dataclass(frozen=True)
class StochasticHealthCriterion:
    """
    Stochastic oscillator health condition.

    """

    max_k: float | None = 80.0
    require_cross: bool = False
    allow_missing: bool = True

    @property
    def name(self) -> str:
        checks: list[str] = []

        if self.max_k is not None:
            checks.append(f"K < {self.max_k}")

        if self.require_cross:
            checks.append("K > D")

        if not checks:
            return "Stochastic Available"

        return f"Stochastic Health ({', '.join(checks)})"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.stochastic is None:
            return self.allow_missing

        stochastic = stock.indicators.stochastic

        if self.max_k is not None:
            if stochastic.k is None:
                return self.allow_missing

            if stochastic.k >= self.max_k:
                return False

        if self.require_cross:
            if stochastic.k is None or stochastic.d is None:
                return self.allow_missing

            if stochastic.k <= stochastic.d:
                return False

        return True
