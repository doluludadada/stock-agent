from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule


class MacdPositiveRule(TradingRule):
    """MACD Line must be positive (above zero line)."""

    @property
    def name(self) -> str:
        return "MACD Above Zero"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.macd is None:
            return False
        if stock.indicators.macd.line is None:
            return False
        return stock.indicators.macd.line > 0
