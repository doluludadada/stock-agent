from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule


class GoldenCrossRule(TradingRule):
    """MA20 recently crossed above MA60 (within margin)."""

    def __init__(self, max_cross_margin: float = 0.03):
        self._max_cross_margin = max_cross_margin

    @property
    def name(self) -> str:
        return "Golden Cross"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.ma is None:
            return False

        ma = stock.indicators.ma
        if ma.ma_20 is None or ma.ma_60 is None:
            return False

        ma_20 = float(ma.ma_20)
        ma_60 = float(ma.ma_60)

        if ma_20 <= ma_60:
            return False

        cross_margin = (ma_20 - ma_60) / ma_60
        return 0 < cross_margin < self._max_cross_margin
