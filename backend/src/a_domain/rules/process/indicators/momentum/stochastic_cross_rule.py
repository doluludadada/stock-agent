from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule


class StochasticCrossRule(TradingRule):
    @property
    def name(self) -> str:
        return "Stochastic Bullish Cross"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.stochastic is None:
            return True
        stoch = stock.indicators.stochastic
        if stoch.k is None or stoch.d is None:
            return True
        return stoch.k > stoch.d
