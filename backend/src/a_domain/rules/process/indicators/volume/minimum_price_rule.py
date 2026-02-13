from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class MinimumPriceRule(TradingRule):
    """Stock price must be above minimum threshold."""

    def __init__(self, min_price: float = 15.0):
        self._min_price = min_price

    @property
    def name(self) -> str:
        return "Minimum Price Check"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.current_price is None:
            return False
        return float(candidate.current_price) >= self._min_price
