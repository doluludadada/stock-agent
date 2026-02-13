from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class BollingerThresholdRule(TradingRule):
    """Price must not be at the upper Bollinger Band."""

    def __init__(self, max_percent_b: float = 0.9):
        self._max_percent_b = max_percent_b

    @property
    def name(self) -> str:
        return "Bollinger Threshold Check"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.indicators is None or candidate.indicators.bollinger is None:
            return True
        if candidate.indicators.bollinger.percent_b is None:
            return True
        return candidate.indicators.bollinger.percent_b < self._max_percent_b
