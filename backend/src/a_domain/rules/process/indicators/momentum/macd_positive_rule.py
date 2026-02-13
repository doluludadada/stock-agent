from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class MacdPositiveRule(TradingRule):
    """MACD Line must be positive (above zero line)."""

    @property
    def name(self) -> str:
        return "MACD Above Zero"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.indicators is None or candidate.indicators.macd is None:
            return False
        if candidate.indicators.macd.line is None:
            return False
        return candidate.indicators.macd.line > 0
