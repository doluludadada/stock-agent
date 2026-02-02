"""
Volatility Rules.

These rules use volatility indicators to time entries and manage risk.

Reference:
- Bollinger, J. (2001). Bollinger on Bollinger Bands.
- Wilder, J.W. (1978). New Concepts in Technical Trading Systems.

Key Principles:
1. Low volatility periods are followed by high volatility (breakouts)
2. High volatility = high risk, need wider stops
3. Bollinger Bands help identify overbought/oversold in context of volatility
"""
from typing import TYPE_CHECKING

from src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from src.a_domain.model.analysis.analysis_context import AnalysisContext


class BollingerNotOverboughtRule(TradingRule):
    """
    Rule: Price must not be at the upper Bollinger Band.
    
    Rationale:
    Price at upper band may be overextended in the short term.
    Wait for pullback to middle band for better entry.
    
    Reference:
    - Bollinger, J. (2001). "Prices near the upper band are relatively high,
      prices near the lower band are relatively low."
    """

    def __init__(self, max_percent_b: float = 0.9):
        """
        Args:
            max_percent_b: Maximum %B (0 = lower band, 1 = upper band)
        """
        self._max_percent_b = max_percent_b

    @property
    def name(self) -> str:
        return f"Bollinger %B < {self._max_percent_b}"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if not hasattr(context, 'bollinger') or context.bollinger is None:
            return True
        if context.bollinger.percent_b is None:
            return True
        return context.bollinger.percent_b < self._max_percent_b


class BollingerAboveMiddleRule(TradingRule):
    """
    Rule: Price should be above the middle Bollinger Band.
    
    Rationale:
    Middle band is the 20-period SMA. Price above middle band
    indicates the short-term trend is bullish.
    
    Reference:
    - Bollinger, J. (2001). "The middle band is the trend indicator.
      Trade in the direction of the middle band."
    """

    @property
    def name(self) -> str:
        return "Price > Bollinger Middle"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if not hasattr(context, 'bollinger') or context.bollinger is None:
            return True
        if context.bollinger.middle is None or context.current_price is None:
            return True
        return context.current_price > context.bollinger.middle


class BollingerSqueezeRule(TradingRule):
    """
    Rule: Bollinger Bands should show squeeze (low volatility).
    
    Rationale:
    Squeeze indicates low volatility, which often precedes a breakout.
    This is the ideal time to position for the next move.
    
    Reference:
    - Bollinger, J. (2001). "When the bands come together, a squeeze,
      a breakout is often around the corner."
    
    Note: Requires bandwidth calculation.
    """

    def __init__(self, max_bandwidth: float = 0.1):
        """
        Args:
            max_bandwidth: Maximum bandwidth for squeeze detection
        """
        self._max_bandwidth = max_bandwidth

    @property
    def name(self) -> str:
        return f"Bollinger Squeeze (bandwidth < {self._max_bandwidth})"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if not hasattr(context, 'bollinger') or context.bollinger is None:
            return True
        if context.bollinger.bandwidth is None:
            return True
        return context.bollinger.bandwidth < self._max_bandwidth


class AtrPositionSizingRule(TradingRule):
    """
    Rule: ATR must be within acceptable range for risk management.
    
    Rationale:
    Very high ATR means high volatility = larger potential losses.
    Very low ATR means the stock is barely moving.
    
    Reference:
    - Wilder, J.W. (1978). "ATR is essential for setting stops
      and calculating position size."
    - Van Tharp (2006). "Position sizing based on ATR ensures
      consistent risk across different volatility levels."
    """

    def __init__(self, min_atr_pct: float = 0.01, max_atr_pct: float = 0.05):
        """
        Args:
            min_atr_pct: Minimum ATR as % of price (1% = some movement)
            max_atr_pct: Maximum ATR as % of price (5% = very volatile)
        """
        self._min_atr_pct = min_atr_pct
        self._max_atr_pct = max_atr_pct

    @property
    def name(self) -> str:
        return f"ATR {self._min_atr_pct*100}%-{self._max_atr_pct*100}%"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if not hasattr(context, 'atr') or context.atr is None:
            return True
        if context.atr.atr_percent is None:
            return True
        return self._min_atr_pct <= context.atr.atr_percent <= self._max_atr_pct


class VolatilityNotExtremeRule(TradingRule):
    """
    Rule: Stock should not be in extreme volatility.
    
    Rationale:
    During extreme volatility (e.g., earnings, news), 
    price can gap significantly. Avoid these situations.
    
    Reference:
    - Elder, A. (1993). "Stay out of extremely volatile situations
      unless you're an experienced scalper."
    """

    def __init__(self, max_daily_range_pct: float = 0.07):
        """
        Args:
            max_daily_range_pct: Maximum (High-Low)/Close (7% default)
        """
        self._max_range = max_daily_range_pct

    @property
    def name(self) -> str:
        return f"Volatility < {self._max_range*100}% daily range"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if not context.ohlcv_data:
            return False
        
        bar = context.ohlcv_data[-1]
        if bar.close_price <= 0:
            return False
        
        daily_range = float(bar.high_price - bar.low_price) / float(bar.close_price)
        return daily_range < self._max_range
