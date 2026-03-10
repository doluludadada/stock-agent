from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule


class IntradayRangeRule(TradingRule):
    def __init__(self, max_range_position: float = 0.8):
        self._max_position = max_range_position

    @property
    def name(self) -> str:
        return "Intraday Range Position"

    def apply(self, stock: Stock) -> bool:
        if stock.today is None:
            return True
        spread = stock.today.high - stock.today.low
        if spread <= 0:
            return True
        position = (stock.today.close - stock.today.low) / spread
        return position < self._max_position
