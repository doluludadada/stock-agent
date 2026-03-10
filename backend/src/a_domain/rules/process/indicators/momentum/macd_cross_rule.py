from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule


class MacdCrossRule(TradingRule):
    """MACD Line must be above Signal Line."""

    @property
    def name(self) -> str:
        return "MACD Bullish Crossover"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.macd is None:
            return False
        macd = stock.indicators.macd
        if macd.line is None or macd.signal is None:
            return False
        return macd.line > macd.signal
