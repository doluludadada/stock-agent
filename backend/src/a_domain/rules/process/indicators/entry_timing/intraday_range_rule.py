from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class IntradayRangeRule(TradingRule):
    """Price should not be at intraday high (buy near support)."""

    def __init__(self, max_range_position: float = 0.8):
        self._max_position = max_range_position

    @property
    def name(self) -> str:
        return "Intraday Range Position"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.intraday_range_position is None:
            return True
        return candidate.intraday_range_position < self._max_position
