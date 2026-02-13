from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule


class AdxDirectionRule(TradingRule):
    """+DI must be greater than -DI (bullish direction)."""

    @property
    def name(self) -> str:
        return "ADX Bullish Direction"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.indicators is None or candidate.indicators.adx is None:
            return True
        adx = candidate.indicators.adx
        if adx.plus_di is None or adx.minus_di is None:
            return True
        return adx.plus_di > adx.minus_di
