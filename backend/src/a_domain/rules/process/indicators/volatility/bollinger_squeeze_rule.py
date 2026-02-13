from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class BollingerSqueezeRule(TradingRule):
    """Bollinger Bands should show squeeze (low volatility, breakout expected)."""

    def __init__(self, max_bandwidth: float = 0.1):
        self._max_bandwidth = max_bandwidth

    @property
    def name(self) -> str:
        return "Bollinger Squeeze"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.indicators is None or candidate.indicators.bollinger is None:
            return True
        if candidate.indicators.bollinger.bandwidth is None:
            return True
        return candidate.indicators.bollinger.bandwidth < self._max_bandwidth
