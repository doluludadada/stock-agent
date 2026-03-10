from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule


class MfiThresholdRule(TradingRule):
    def __init__(self, threshold: float = 80.0):
        self._threshold = threshold

    @property
    def name(self) -> str:
        return "MFI Not Overbought"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.mfi is None:
            return True
        if stock.indicators.mfi.mfi_14 is None:
            return True
        return stock.indicators.mfi.mfi_14 < self._threshold
