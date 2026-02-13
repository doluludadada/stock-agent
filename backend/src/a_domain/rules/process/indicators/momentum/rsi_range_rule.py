from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class RsiRangeRule(TradingRule):
    """RSI must be within specified range."""

    def __init__(self, min_rsi: float = 0.0, max_rsi: float = 100.0):
        self._min_rsi = min_rsi
        self._max_rsi = max_rsi

    @property
    def name(self) -> str:
        return "RSI Range Check"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.indicators is None or candidate.indicators.rsi is None:
            return False
        if candidate.indicators.rsi.val_14 is None:
            return False
        return self._min_rsi <= candidate.indicators.rsi.val_14 <= self._max_rsi
