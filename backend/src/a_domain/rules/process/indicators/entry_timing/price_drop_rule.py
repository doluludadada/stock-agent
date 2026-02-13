from decimal import Decimal
from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class PriceDropRule(TradingRule):
    """Stock should not be crashing today."""

    def __init__(self, max_drop_pct: float = 0.03):
        self._max_drop = Decimal(str(max_drop_pct))

    @property
    def name(self) -> str:
        return "Price Drop Check"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.price_change_pct is None:
            return False
        return candidate.price_change_pct > -self._max_drop
