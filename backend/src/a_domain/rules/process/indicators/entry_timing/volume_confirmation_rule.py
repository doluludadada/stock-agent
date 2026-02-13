from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class VolumeConfirmationRule(TradingRule):
    """Today's volume should confirm buying interest."""

    def __init__(self, min_volume_ratio: float = 0.5):
        self._min_ratio = min_volume_ratio

    @property
    def name(self) -> str:
        return "Volume Confirmation"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.indicators is None or candidate.indicators.ma is None:
            return True
        if candidate.indicators.ma.volume_ma_5 is None:
            return True
        if not candidate.ohlcv_data:
            return False
        today_volume = candidate.ohlcv_data[-1].volume
        avg_volume = candidate.indicators.ma.volume_ma_5
        if avg_volume <= 0:
            return True
        return today_volume >= (avg_volume * self._min_ratio)
