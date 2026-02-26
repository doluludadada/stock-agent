from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule


class DailyRangeRule(TradingRule):
    """Stock should not be in extreme volatility."""

    def __init__(self, max_daily_range_pct: float = 0.07):
        self._max_range = max_daily_range_pct

    @property
    def name(self) -> str:
        return "Daily Range Check"

    def apply(self, stock: Stock) -> bool:
        if stock.today is None:
            return False
        if stock.today.low <= 0:
            return False
        daily_range = float((stock.today.high - stock.today.low) / stock.today.low)
        return daily_range < self._max_range
