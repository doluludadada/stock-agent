from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class DailyRangeRule(TradingRule):
    """Stock should not be in extreme volatility."""

    def __init__(self, max_daily_range_pct: float = 0.07):
        self._max_range = max_daily_range_pct

    @property
    def name(self) -> str:
        return "Daily Range Check"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.daily_range_pct is None:
            return False
        return candidate.daily_range_pct < self._max_range
