from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class StochasticThresholdRule(TradingRule):
    """Stochastic %K must not be overbought."""

    def __init__(self, threshold: float = 80.0):
        self._threshold = threshold

    @property
    def name(self) -> str:
        return "Stochastic Not Overbought"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.indicators is None or candidate.indicators.stochastic is None:
            return True
        if candidate.indicators.stochastic.k is None:
            return True
        return candidate.indicators.stochastic.k < self._threshold
