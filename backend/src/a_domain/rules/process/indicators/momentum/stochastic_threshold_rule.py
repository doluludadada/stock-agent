from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule


class StochasticThresholdRule(TradingRule):
    def __init__(self, threshold: float = 80.0):
        self._threshold = threshold

    @property
    def name(self) -> str:
        return "Stochastic Not Overbought"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.stochastic is None:
            return True
        if stock.indicators.stochastic.k is None:
            return True
        return stock.indicators.stochastic.k < self._threshold
