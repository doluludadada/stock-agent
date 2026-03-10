from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule


class MinimumPriceRule(TradingRule):
    def __init__(self, min_price: float = 15.0):
        self._min_price = min_price

    @property
    def name(self) -> str:
        return "Minimum Price Check"

    def apply(self, stock: Stock) -> bool:
        if stock.current_price is None:
            return False
        return stock.current_price >= self._min_price
