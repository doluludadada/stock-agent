from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule


class IntradayMomentumRule(TradingRule):
    """Current price should be above today's open."""

    @property
    def name(self) -> str:
        return "Intraday Momentum"

    def apply(self, stock: Stock) -> bool:
        if stock.today is None:
            return False
        if stock.today.open <= 0:
            return False
        return stock.today.close > stock.today.open
