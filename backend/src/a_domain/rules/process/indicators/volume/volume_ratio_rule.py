from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class VolumeRatioRule(TradingRule):
    """Current volume must meet the minimum ratio vs average volume."""

    def __init__(self, min_ratio: float = 1.0):
        self._min_ratio = min_ratio

    @property
    def name(self) -> str:
        return "Volume Ratio Check"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.indicators is None or candidate.indicators.ma is None:
            return False
        avg_volume = candidate.indicators.ma.volume_ma_5
        if avg_volume is None:
            return True
        if not candidate.ohlcv_data:
            return False
        current_volume = candidate.ohlcv_data[-1].volume
        if avg_volume <= 0:
            return False
        return current_volume >= (avg_volume * self._min_ratio)
