from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule


class VolumeConfirmationRule(TradingRule):
    def __init__(self, min_volume_ratio: float = 0.5):
        self._min_ratio = min_volume_ratio

    @property
    def name(self) -> str:
        return "Volume Confirmation"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.ma is None:
            return True
        if stock.indicators.ma.volume_ma_5 is None:
            return True
        if not stock.ohlcv:
            return False
        today_volume = stock.ohlcv[-1].volume
        avg_volume = stock.indicators.ma.volume_ma_5
        if avg_volume <= 0:
            return True
        return today_volume >= (avg_volume * self._min_ratio)
