from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class MacdCrossRule(TradingRule):
    """MACD Line must be above Signal Line."""

    @property
    def name(self) -> str:
        return "MACD Bullish Crossover"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.indicators is None or candidate.indicators.macd is None:
            return False
        macd = candidate.indicators.macd
        if macd.line is None or macd.signal is None:
            return False
        return macd.line > macd.signal
