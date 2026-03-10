from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule
from a_domain.rules.process.indicators.utils import get_ma_value
from a_domain.types.enums import MaPeriod


class MaAlignmentRule(TradingRule):
    """Fast MA must be above slow MA (bullish alignment)."""

    def __init__(self, fast: MaPeriod = MaPeriod.MA_20, slow: MaPeriod = MaPeriod.MA_60):
        self._fast = fast
        self._slow = slow

    @property
    def name(self) -> str:
        return f"{self._fast.value} > {self._slow.value} Alignment"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.ma is None:
            return False
        fast_val = get_ma_value(stock.indicators.ma, self._fast)
        slow_val = get_ma_value(stock.indicators.ma, self._slow)
        if fast_val is None or slow_val is None:
            return False
        return fast_val > slow_val
