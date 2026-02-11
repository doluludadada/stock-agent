"""
Entry Timing Rules.

Used ONLY during intraday trading to ensure the exact entry moment is optimal.

Reference:
- Elder, A. (1993). Trading for a Living.
- Schwartz, M. (1998). Pit Bull.
- Connors, L. & Raschke, L. (1995). Street Smarts.
"""
from decimal import Decimal
from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.analysis.stock_candidate import StockCandidate


class PriceDropRule(TradingRule):
    """Stock should not be crashing today."""

    def __init__(self, max_drop_pct: float = 0.03):
        self._max_drop = Decimal(str(max_drop_pct))

    @property
    def name(self) -> str:
        return "Price Drop Check"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.current_price is None or not candidate.ohlcv_data:
            return False
        if len(candidate.ohlcv_data) < 2:
            return False
        yesterday_close = candidate.ohlcv_data[-2].close_price
        if yesterday_close <= 0:
            return False
        change = (candidate.current_price - yesterday_close) / yesterday_close
        return change > -self._max_drop


class IntradayMomentumRule(TradingRule):
    """Current price should be above today's open."""

    @property
    def name(self) -> str:
        return "Intraday Momentum"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.current_price is None or not candidate.ohlcv_data:
            return False
        today_open = candidate.ohlcv_data[-1].open_price
        if today_open <= 0:
            return False
        return candidate.current_price > today_open


class VolumeConfirmationRule(TradingRule):
    """Today's volume should confirm buying interest."""

    def __init__(self, min_volume_ratio: float = 0.5):
        self._min_ratio = min_volume_ratio

    @property
    def name(self) -> str:
        return "Volume Confirmation"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
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


class GapRule(TradingRule):
    """Stock should not have gapped up excessively."""

    def __init__(self, max_gap_pct: float = 0.03):
        self._max_gap = max_gap_pct

    @property
    def name(self) -> str:
        return "Gap Check"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if not candidate.ohlcv_data or len(candidate.ohlcv_data) < 2:
            return True
        yesterday_close = candidate.ohlcv_data[-2].close_price
        today_open = candidate.ohlcv_data[-1].open_price
        if yesterday_close <= 0:
            return True
        gap = float(today_open - yesterday_close) / float(yesterday_close)
        return gap < self._max_gap


class IntradayRangeRule(TradingRule):
    """Price should not be at intraday high (buy near support)."""

    def __init__(self, max_range_position: float = 0.8):
        self._max_position = max_range_position

    @property
    def name(self) -> str:
        return "Intraday Range Position"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.current_price is None or not candidate.ohlcv_data:
            return True
        bar = candidate.ohlcv_data[-1]
        intraday_range = bar.high_price - bar.low_price
        if intraday_range <= 0:
            return True
        position = float(candidate.current_price - bar.low_price) / float(intraday_range)
        return position < self._max_position


class ConsecutiveUpDaysRule(TradingRule):
    """Avoid buying after too many consecutive up days."""

    def __init__(self, max_consecutive_up: int = 4):
        self._max_up = max_consecutive_up

    @property
    def name(self) -> str:
        return "Consecutive Up Days Check"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if not candidate.ohlcv_data or len(candidate.ohlcv_data) < self._max_up + 1:
            return True
        up_count = 0
        for i in range(len(candidate.ohlcv_data) - 1, 0, -1):
            if candidate.ohlcv_data[i].close_price > candidate.ohlcv_data[i - 1].close_price:
                up_count += 1
            else:
                break
        return up_count < self._max_up
