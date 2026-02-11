"""
Volatility Rules.

Reference:
- Bollinger, J. (2001). Bollinger on Bollinger Bands.
- Wilder, J.W. (1978). New Concepts in Technical Trading Systems.
"""
from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.analysis.stock_candidate import StockCandidate


class BollingerThresholdRule(TradingRule):
    """Price must not be at the upper Bollinger Band."""

    def __init__(self, max_percent_b: float = 0.9):
        self._max_percent_b = max_percent_b

    @property
    def name(self) -> str:
        return "Bollinger Threshold Check"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.bollinger is None:
            return True
        if candidate.indicators.bollinger.percent_b is None:
            return True
        return candidate.indicators.bollinger.percent_b < self._max_percent_b


class BollingerPositionRule(TradingRule):
    """Price should be above the middle Bollinger Band."""

    @property
    def name(self) -> str:
        return "Bollinger Above Middle"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.bollinger is None:
            return True
        bb = candidate.indicators.bollinger
        if bb.middle is None or candidate.current_price is None:
            return True
        return candidate.current_price > bb.middle


class BollingerSqueezeRule(TradingRule):
    """Bollinger Bands should show squeeze (low volatility, breakout expected)."""

    def __init__(self, max_bandwidth: float = 0.1):
        self._max_bandwidth = max_bandwidth

    @property
    def name(self) -> str:
        return "Bollinger Squeeze"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.bollinger is None:
            return True
        if candidate.indicators.bollinger.bandwidth is None:
            return True
        return candidate.indicators.bollinger.bandwidth < self._max_bandwidth


class AtrRangeRule(TradingRule):
    """ATR must be within acceptable range for risk management."""

    def __init__(self, min_atr_pct: float = 0.01, max_atr_pct: float = 0.05):
        self._min_atr_pct = min_atr_pct
        self._max_atr_pct = max_atr_pct

    @property
    def name(self) -> str:
        return "ATR Position Sizing"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.atr is None:
            return True
        if candidate.indicators.atr.atr_percent is None:
            return True
        return self._min_atr_pct <= candidate.indicators.atr.atr_percent <= self._max_atr_pct


class DailyRangeRule(TradingRule):
    """Stock should not be in extreme volatility."""

    def __init__(self, max_daily_range_pct: float = 0.07):
        self._max_range = max_daily_range_pct

    @property
    def name(self) -> str:
        return "Daily Range Check"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if not candidate.ohlcv_data:
            return False
        bar = candidate.ohlcv_data[-1]
        if bar.close_price <= 0:
            return False
        daily_range = float(bar.high_price - bar.low_price) / float(bar.close_price)
        return daily_range < self._max_range
