from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class BollingerPositionRule(TradingRule):
    """Price should be above the middle Bollinger Band."""

    @property
    def name(self) -> str:
        return "Bollinger Above Middle"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.indicators is None or candidate.indicators.bollinger is None:
            return True
        bb = candidate.indicators.bollinger
        if bb.middle is None or candidate.current_price is None:
            return True
        return candidate.current_price > bb.middle
