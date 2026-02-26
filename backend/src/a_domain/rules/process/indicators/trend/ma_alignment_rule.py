from decimal import Decimal

from backend.src.a_domain.model.indicators.technical_indicators import MovingAverages
from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule
from backend.src.a_domain.types.enums import MaPeriod


class MaAlignmentRule(TradingRule):
    """Fast MA must be above slow MA (bullish alignment)."""

    def __init__(self, fast: MaPeriod = MaPeriod.MA_20, slow: MaPeriod = MaPeriod.MA_60):
        self._fast = fast
        self._slow = slow

    @property
    def name(self) -> str:
        return f"{self._fast.value} > {self._slow.value} Alignment"

    def _get_ma_value(self, ma: MovingAverages, period: MaPeriod) -> Decimal | None:
        match period:
            case MaPeriod.MA_5:
                return ma.ma_5
            case MaPeriod.MA_10:
                return ma.ma_10
            case MaPeriod.MA_20:
                return ma.ma_20
            case MaPeriod.MA_60:
                return ma.ma_60
            case MaPeriod.MA_120:
                return ma.ma_120
            case _:
                return None

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.ma is None:
            return False
        ma = stock.indicators.ma
        fast_val = self._get_ma_value(ma, self._fast)
        slow_val = self._get_ma_value(ma, self._slow)
        if fast_val is None or slow_val is None:
            return False
        return fast_val > slow_val
