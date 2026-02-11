"""
Volume Rules.

Reference:
- Granville, J. (1963). Granville's New Key to Stock Market Profits.
- Murphy, J. (1999). Technical Analysis of the Financial Markets, Chapter 7.
"""
from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.analysis.stock_candidate import StockCandidate


class VolumeRatioRule(TradingRule):
    """Current volume must meet the minimum ratio vs average volume."""

    def __init__(self, min_ratio: float = 1.0):
        self._min_ratio = min_ratio

    @property
    def name(self) -> str:
        return "Volume Ratio Check"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
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


class ObvTrendRule(TradingRule):
    """On-Balance Volume (OBV) should be above its 20-day MA (rising trend)."""

    @property
    def name(self) -> str:
        return "OBV Trend"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.obv is None:
            return True
        obv = candidate.indicators.obv
        if obv.obv is None or obv.obv_ma_20 is None:
            return True
        return obv.obv > obv.obv_ma_20


class LiquidityRule(TradingRule):
    """Stock must have minimum daily trading volume."""

    def __init__(self, min_daily_volume: int = 500):
        self._min_volume = min_daily_volume

    @property
    def name(self) -> str:
        return "Liquidity Check"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if not candidate.ohlcv_data:
            return False
        recent_volumes = [bar.volume for bar in candidate.ohlcv_data[-5:]]
        if not recent_volumes:
            return False
        avg_volume = sum(recent_volumes) / len(recent_volumes)
        return avg_volume >= self._min_volume


class MinimumPriceRule(TradingRule):
    """Stock price must be above minimum threshold."""

    def __init__(self, min_price: float = 15.0):
        self._min_price = min_price

    @property
    def name(self) -> str:
        return "Minimum Price Check"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.current_price is None:
            return False
        return float(candidate.current_price) >= self._min_price
