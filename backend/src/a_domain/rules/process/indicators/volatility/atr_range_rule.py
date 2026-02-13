from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class AtrRangeRule(TradingRule):
    """ATR must be within acceptable range for risk management."""

    def __init__(self, min_atr_pct: float = 0.01, max_atr_pct: float = 0.05):
        self._min_atr_pct = min_atr_pct
        self._max_atr_pct = max_atr_pct

    @property
    def name(self) -> str:
        return "ATR Position Sizing"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.indicators is None or candidate.indicators.atr is None:
            return True
        if candidate.indicators.atr.atr_percent is None:
            return True
        return self._min_atr_pct <= candidate.indicators.atr.atr_percent <= self._max_atr_pct
