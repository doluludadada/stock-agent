from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule


class AdxDirectionRule(TradingRule):
    """+DI must be greater than -DI (bullish direction)."""

    @property
    def name(self) -> str:
        return "ADX Bullish Direction"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.adx is None:
            return True
        adx = stock.indicators.adx
        if adx.plus_di is None or adx.minus_di is None:
            return True
        return adx.plus_di > adx.minus_di
