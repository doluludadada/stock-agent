from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule


class AdxTrendStrengthRule(TradingRule):
    """ADX must indicate a trending market (not range-bound, not exhausted)."""

    def __init__(self, min_adx: float = 20.0, max_adx: float = 50.0):
        self._min_adx = min_adx
        self._max_adx = max_adx

    @property
    def name(self) -> str:
        return "ADX Trend Strength"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.indicators is None or candidate.indicators.adx is None:
            return True
        if candidate.indicators.adx.adx is None:
            return True
        return self._min_adx <= candidate.indicators.adx.adx <= self._max_adx
