from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule


class BollingerThresholdRule(TradingRule):
    """Price must not be at the upper Bollinger Band."""

    def __init__(self, max_percent_b: float = 0.9):
        self._max_percent_b = max_percent_b

    @property
    def name(self) -> str:
        return "Bollinger Threshold Check"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.bollinger is None:
            return True
        if stock.indicators.bollinger.percent_b is None:
            return True
        return stock.indicators.bollinger.percent_b < self._max_percent_b
