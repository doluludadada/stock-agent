from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule


class ConsecutiveUpDaysRule(TradingRule):
    """Avoid buying after too many consecutive up days."""

    def __init__(self, max_consecutive_up: int = 4):
        self._max_up = max_consecutive_up

    @property
    def name(self) -> str:
        return "Consecutive Up Days Check"

    def apply(self, stock: Stock) -> bool:
        bars = stock.ohlcv
        if len(bars) < self._max_up + 1:
            return True

        count = 0
        for i in range(len(bars) - 1, 0, -1):
            if bars[i].close > bars[i - 1].close:
                count += 1
            else:
                break

        return count < self._max_up
