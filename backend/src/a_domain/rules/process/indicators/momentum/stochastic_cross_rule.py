from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class StochasticCrossRule(TradingRule):
    """Stochastic %K must be above %D (bullish crossover)."""

    @property
    def name(self) -> str:
        return "Stochastic Bullish Cross"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.indicators is None or candidate.indicators.stochastic is None:
            return True
        stoch = candidate.indicators.stochastic
        if stoch.k is None or stoch.d is None:
            return True
        return stoch.k > stoch.d
