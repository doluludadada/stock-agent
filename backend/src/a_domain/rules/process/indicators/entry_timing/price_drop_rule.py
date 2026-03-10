from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule


class PriceDropRule(TradingRule):
    """Stock should not be crashing today."""

    def __init__(self, max_drop_pct: float = 0.03):
        self._max_drop = max_drop_pct

    @property
    def name(self) -> str:
        return "Price Drop Check"

    def apply(self, stock: Stock) -> bool:
        if stock.today is None or stock.yesterday is None:
            return False
        if stock.yesterday.close == 0:
            return False
        change = (stock.today.close - stock.yesterday.close) / stock.yesterday.close
        return change > -self._max_drop
