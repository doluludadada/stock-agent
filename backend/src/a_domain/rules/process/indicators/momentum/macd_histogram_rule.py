from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class MacdHistogramRule(TradingRule):
    """MACD Histogram should be positive (momentum increasing)."""

    @property
    def name(self) -> str:
        return "MACD Histogram Rising"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.indicators is None or candidate.indicators.macd is None:
            return True
        if candidate.indicators.macd.histogram is None:
            return True
        return candidate.indicators.macd.histogram > 0
