from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule


class AtrRangeRule(TradingRule):
    def __init__(self, min_atr_pct: float = 0.01, max_atr_pct: float = 0.05):
        self._min_atr_pct = min_atr_pct
        self._max_atr_pct = max_atr_pct

    @property
    def name(self) -> str:
        return "ATR Position Sizing"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.atr is None:
            return True
        if stock.indicators.atr.atr_percent is None:
            return True
        return self._min_atr_pct <= stock.indicators.atr.atr_percent <= self._max_atr_pct
