from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule


class RsiRangeRule(TradingRule):
    """RSI must be within specified range."""

    def __init__(self, min_rsi: float = 0.0, max_rsi: float = 100.0):
        self._min_rsi = min_rsi
        self._max_rsi = max_rsi

    @property
    def name(self) -> str:
        return "RSI Range Check"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.rsi is None:
            return False
        if stock.indicators.rsi.val_14 is None:
            return False
        return self._min_rsi <= stock.indicators.rsi.val_14 <= self._max_rsi
