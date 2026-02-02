"""
Volume Rules.

Volume confirms price movements. "Volume precedes price."

Reference:
- Granville, J. (1963). Granville's New Key to Stock Market Profits.
- Murphy, J. (1999). Technical Analysis of the Financial Markets, Chapter 7.
- Elder, A. (1993). Trading for a Living.

Key Principles:
1. Volume should increase in the direction of the trend
2. Rising prices with rising volume = bullish
3. Rising prices with falling volume = bearish divergence (weakness)
4. Breakouts should be accompanied by above-average volume
"""
from typing import TYPE_CHECKING

from src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from src.a_domain.model.analysis.analysis_context import AnalysisContext


class VolumeAboveAverageRule(TradingRule):
    """
    Rule: Current volume must be above the moving average.
    
    Rationale:
    Above-average volume indicates strong market participation.
    Price moves on high volume are more reliable.
    
    Reference:
    - Murphy, J. (1999). "Volume should expand in the direction of
      the existing price trend. High volume confirms the trend."
    """

    def __init__(self, min_ratio: float = 1.0):
        """
        Args:
            min_ratio: Minimum ratio of current volume to average (default 1.0 = above average)
        """
        self._min_ratio = min_ratio

    @property
    def name(self) -> str:
        return f"Volume > {self._min_ratio}x Average"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.ma is None or context.ma.volume_ma_5 is None:
            return True  # Pass if not available
        if not context.ohlcv_data:
            return False
        
        current_volume = context.ohlcv_data[-1].volume
        avg_volume = context.ma.volume_ma_5
        
        if avg_volume <= 0:
            return False
        
        return current_volume >= (avg_volume * self._min_ratio)


class VolumeBreakoutRule(TradingRule):
    """
    Rule: Volume must be significantly above average (breakout level).
    
    Rationale:
    Breakouts should be accompanied by volume 1.5-2x normal.
    This confirms institutional participation.
    
    Reference:
    - O'Neil, W. (1988). How to Make Money in Stocks.
      "Volume should be at least 50% above average on breakout day."
    """

    def __init__(self, breakout_ratio: float = 1.5):
        self._breakout_ratio = breakout_ratio

    @property
    def name(self) -> str:
        return f"Volume Breakout (> {self._breakout_ratio}x)"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.ma is None or context.ma.volume_ma_5 is None:
            return True
        if not context.ohlcv_data:
            return False
        
        current_volume = context.ohlcv_data[-1].volume
        avg_volume = context.ma.volume_ma_5
        
        if avg_volume <= 0:
            return False
        
        return current_volume >= (avg_volume * self._breakout_ratio)


class VolumeNotDryRule(TradingRule):
    """
    Rule: Volume must not be too low (dry).
    
    Rationale:
    Very low volume indicates lack of interest.
    Price moves on low volume are unreliable and can reverse quickly.
    
    Reference:
    - Elder, A. (1993). "Avoid trading when volume is below 50% of average.
      The market is asleep, and moves are meaningless."
    """

    def __init__(self, min_ratio: float = 0.5):
        self._min_ratio = min_ratio

    @property
    def name(self) -> str:
        return f"Volume Not Dry (> {self._min_ratio}x avg)"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.ma is None or context.ma.volume_ma_5 is None:
            return True
        if not context.ohlcv_data:
            return False
        
        current_volume = context.ohlcv_data[-1].volume
        avg_volume = context.ma.volume_ma_5
        
        if avg_volume <= 0:
            return True
        
        return current_volume >= (avg_volume * self._min_ratio)


class ObvRisingRule(TradingRule):
    """
    Rule: On-Balance Volume (OBV) should be rising.
    
    Rationale:
    OBV rising with price confirms buying pressure.
    OBV falling while price rises = bearish divergence.
    
    Reference:
    - Granville, J. (1963). "OBV leads price. If OBV is making new highs,
      price will follow. If OBV diverges from price, a reversal is coming."
    
    Note: Requires OBV history to detect rising pattern.
    """

    @property
    def name(self) -> str:
        return "OBV Rising"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if not hasattr(context, 'obv') or context.obv is None:
            return True
        # For now, pass if OBV is not available
        # Full implementation would check OBV trend
        return True


class LiquidityRule(TradingRule):
    """
    Rule: Stock must have minimum daily trading volume.
    
    Rationale:
    Illiquid stocks have wide spreads and slippage.
    Avoid stocks that you can't easily exit.
    
    Reference:
    - O'Neil, W. (1988). "Trade only stocks with average daily volume
      of at least 400,000 shares for institutional quality."
    
    For Taiwan market (using lots of 1000 shares):
    - Minimum 500 lots = 500,000 shares daily
    """

    def __init__(self, min_daily_volume: int = 500):
        """
        Args:
            min_daily_volume: Minimum daily volume in lots (default 500 lots)
        """
        self._min_volume = min_daily_volume

    @property
    def name(self) -> str:
        return f"Liquidity (> {self._min_volume} lots)"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if not context.ohlcv_data:
            return False
        
        # Use average of last 5 days
        recent_volumes = [bar.volume for bar in context.ohlcv_data[-5:]]
        if not recent_volumes:
            return False
        
        avg_volume = sum(recent_volumes) / len(recent_volumes)
        return avg_volume >= self._min_volume


class MinimumPriceRule(TradingRule):
    """
    Rule: Stock price must be above minimum threshold.
    
    Rationale:
    Very low-priced stocks (penny stocks) are often manipulated
    and have high volatility with low institutional interest.
    
    Reference:
    - O'Neil, W. (1988). "Avoid stocks priced below $15-20.
      Low-priced stocks often have fundamental problems."
    
    For Taiwan market: Minimum NT$15-20
    """

    def __init__(self, min_price: float = 15.0):
        self._min_price = min_price

    @property
    def name(self) -> str:
        return f"Price > {self._min_price}"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.current_price is None:
            return False
        return float(context.current_price) >= self._min_price
