from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule


class IntradayMomentumRule(TradingRule):
    @property
    def name(self) -> str:
        return "Intraday Momentum"

    def apply(self, stock: Stock) -> bool:
        if stock.today is None:
            return False
        if stock.today.open <= 0:
            return False
        return stock.today.close > stock.today.open
