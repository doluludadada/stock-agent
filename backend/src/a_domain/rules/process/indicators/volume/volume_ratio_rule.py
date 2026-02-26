from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule


class VolumeRatioRule(TradingRule):
    """Current volume must meet the minimum ratio vs average volume."""

    def __init__(self, min_ratio: float = 1.0):
        self._min_ratio = min_ratio

    @property
    def name(self) -> str:
        return "Volume Ratio Check"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.ma is None:
            return False
        avg_volume = stock.indicators.ma.volume_ma_5
        if avg_volume is None:
            return True
        if not stock.ohlcv:
            return False
        current_volume = stock.ohlcv[-1].volume
        if avg_volume <= 0:
            return False
        return current_volume >= (avg_volume * self._min_ratio)
