from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule


class MacdHistogramRule(TradingRule):
    """MACD Histogram should be positive (momentum increasing)."""

    @property
    def name(self) -> str:
        return "MACD Histogram Rising"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.macd is None:
            return True
        if stock.indicators.macd.histogram is None:
            return True
        return stock.indicators.macd.histogram > 0
