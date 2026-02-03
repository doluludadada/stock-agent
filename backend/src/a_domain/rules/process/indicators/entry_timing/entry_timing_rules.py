"""
Entry Timing Rules.

These rules are used ONLY during intraday trading to ensure
the exact entry moment is optimal.

The setup may be perfect, but bad entry timing can still lose money.

Reference:
- Elder, A. (1993). Trading for a Living.
  "The Triple Screen Trading System: Use weekly charts to identify trend,
  daily charts for timing, intraday for entry."
  
- Schwartz, M. (1998). Pit Bull.
  "The entry is everything. A great trade with bad entry becomes mediocre."
"""
from decimal import Decimal
from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.analysis.analysis_context import AnalysisContext


class NotCrashingRule(TradingRule):
    """
    Rule: Stock should not be crashing today.
    
    Rationale:
    Even if daily setup is perfect, don't catch a falling knife.
    Wait for price to stabilize before entering.
    
    Reference:
    - Livermore, J. (1940). How to Trade in Stocks.
      "Never buy on the way down. Wait for the bottom to form."
    """

    def __init__(self, max_drop_pct: float = 0.03):
        """
        Args:
            max_drop_pct: Maximum allowed drop from yesterday's close (3% default)
        """
        self._max_drop = Decimal(str(max_drop_pct))

    @property
    def name(self) -> str:
        return f"Not Crashing (< {self._max_drop*100}% drop)"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.current_price is None or not context.ohlcv_data:
            return False
        
        if len(context.ohlcv_data) < 2:
            return False
        
        yesterday_close = context.ohlcv_data[-2].close_price
        if yesterday_close <= 0:
            return False
        
        change = (context.current_price - yesterday_close) / yesterday_close
        return change > -self._max_drop


class IntradayMomentumRule(TradingRule):
    """
    Rule: Current price should be above today's open.
    
    Rationale:
    Price above open = buyers are stronger than sellers today.
    Price below open = sellers are stronger, don't buy into weakness.
    
    Reference:
    - Schwartz, M. (1998). "If a stock is trading below its open,
      sellers are in control. Wait for strength."
    """

    @property
    def name(self) -> str:
        return "Price > Today's Open"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.current_price is None or not context.ohlcv_data:
            return False
        
        today_open = context.ohlcv_data[-1].open_price
        if today_open <= 0:
            return False
        
        return context.current_price > today_open


class VolumeConfirmationRule(TradingRule):
    """
    Rule: Today's volume should confirm buying interest.
    
    Rationale:
    Low volume moves are unreliable. Need volume confirmation.
    
    Reference:
    - Murphy, J. (1999). "Volume should confirm price. Rising prices
      should be accompanied by rising volume."
    """

    def __init__(self, min_volume_ratio: float = 0.5):
        """
        Args:
            min_volume_ratio: Minimum ratio to 5-day average volume
        """
        self._min_ratio = min_volume_ratio

    @property
    def name(self) -> str:
        return f"Volume > {self._min_ratio*100}% of avg"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.ma is None or context.ma.volume_ma_5 is None:
            return True
        if not context.ohlcv_data:
            return False
        
        today_volume = context.ohlcv_data[-1].volume
        avg_volume = context.ma.volume_ma_5
        
        if avg_volume <= 0:
            return True
        
        return today_volume >= (avg_volume * self._min_ratio)


class NotGappedUpExcessivelyRule(TradingRule):
    """
    Rule: Stock should not have gapped up excessively.
    
    Rationale:
    Large gaps up are often filled (price comes back down).
    Buying after a big gap is risky.
    
    Reference:
    - Elder, A. (1993). "Gaps are often filled. After a big gap up,
      wait for a pullback before buying."
    """

    def __init__(self, max_gap_pct: float = 0.03):
        """
        Args:
            max_gap_pct: Maximum gap from yesterday's close to today's open
        """
        self._max_gap = max_gap_pct

    @property
    def name(self) -> str:
        return f"Gap < {self._max_gap*100}%"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if not context.ohlcv_data or len(context.ohlcv_data) < 2:
            return True
        
        yesterday_close = context.ohlcv_data[-2].close_price
        today_open = context.ohlcv_data[-1].open_price
        
        if yesterday_close <= 0:
            return True
        
        gap = float(today_open - yesterday_close) / float(yesterday_close)
        return gap < self._max_gap


class IntradayRangePositionRule(TradingRule):
    """
    Rule: Price should not be at intraday high (buy near support).
    
    Rationale:
    Buying at the intraday high means you're the last buyer.
    Better to buy on pullback within the day's range.
    
    Reference:
    - Schwartz, M. (1998). "Never chase. Let the market come to you."
    """

    def __init__(self, max_range_position: float = 0.8):
        """
        Args:
            max_range_position: Maximum position in today's range (0=low, 1=high)
        """
        self._max_position = max_range_position

    @property
    def name(self) -> str:
        return f"Not at Intraday High (< {self._max_position*100}%)"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.current_price is None or not context.ohlcv_data:
            return True
        
        bar = context.ohlcv_data[-1]
        intraday_range = bar.high_price - bar.low_price
        
        if intraday_range <= 0:
            return True
        
        position = float(context.current_price - bar.low_price) / float(intraday_range)
        return position < self._max_position


class TradingHoursRule(TradingRule):
    """
    Rule: Only trade during optimal hours.
    
    Rationale:
    - First 30 minutes: High volatility, amateur hour
    - Last 30 minutes: Institutional activity, reliable moves
    - Midday: Low volume, choppy
    
    Reference:
    - Elder, A. (1993). "The best time to trade is the first hour
      and the last hour. Avoid the midday doldrums."
    
    Note: Requires current time, not implemented in context.
    """

    def __init__(self, avoid_first_minutes: int = 30, avoid_last_minutes: int = 15):
        self._avoid_first = avoid_first_minutes
        self._avoid_last = avoid_last_minutes

    @property
    def name(self) -> str:
        return "Within Optimal Trading Hours"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        # This requires current time which isn't in the context
        # For now, always pass
        return True


class ConsecutiveUpDaysRule(TradingRule):
    """
    Rule: Avoid buying after too many consecutive up days.
    
    Rationale:
    After 5+ consecutive up days, a pullback is likely.
    Wait for consolidation before entering.
    
    Reference:
    - Connors, L. & Raschke, L. (1995). Street Smarts.
      "After 4 consecutive higher closes, the probability of
      continuation drops significantly."
    """

    def __init__(self, max_consecutive_up: int = 4):
        self._max_up = max_consecutive_up

    @property
    def name(self) -> str:
        return f"< {self._max_up} Consecutive Up Days"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if not context.ohlcv_data or len(context.ohlcv_data) < self._max_up + 1:
            return True
        
        # Count consecutive up days
        up_count = 0
        for i in range(len(context.ohlcv_data) - 1, 0, -1):
            if context.ohlcv_data[i].close_price > context.ohlcv_data[i-1].close_price:
                up_count += 1
            else:
                break
        
        return up_count < self._max_up


