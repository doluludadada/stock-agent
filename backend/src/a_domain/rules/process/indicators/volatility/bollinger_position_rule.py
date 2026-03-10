from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule


class BollingerPositionRule(TradingRule):
    @property
    def name(self) -> str:
        return "Bollinger Above Middle"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.bollinger is None:
            return True
        bb = stock.indicators.bollinger
        if bb.middle is None or stock.current_price is None:
            return True
        return stock.current_price > bb.middle
