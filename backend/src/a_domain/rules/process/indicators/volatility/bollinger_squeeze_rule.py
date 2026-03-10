from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule


class BollingerSqueezeRule(TradingRule):
    def __init__(self, max_bandwidth: float = 0.1):
        self._max_bandwidth = max_bandwidth

    @property
    def name(self) -> str:
        return "Bollinger Squeeze"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.bollinger is None:
            return True
        if stock.indicators.bollinger.bandwidth is None:
            return True
        return stock.indicators.bollinger.bandwidth < self._max_bandwidth
