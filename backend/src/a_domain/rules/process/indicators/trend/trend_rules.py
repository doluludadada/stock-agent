"""
Trend Following Rules.

These rules identify whether a stock is in an uptrend suitable for buying.

Reference:
- Murphy, J. (1999). Technical Analysis of the Financial Markets, Chapter 9.
  "The trend is your friend" - Trade in the direction of the trend.
  
- Elder, A. (1993). Trading for a Living, Chapter 5.
  "Use moving averages to identify the trend, then use oscillators to find entry points."
"""
from decimal import Decimal
from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.analysis.analysis_context import AnalysisContext


class PriceAboveMa20Rule(TradingRule):
    """
    Rule: Price must be above the 20-period Moving Average.
    
    Rationale:
    The 20-day MA represents the average price over the past month.
    Price above MA20 indicates short-term bullish momentum.
    
    Reference:
    - Murphy, J. (1999). "The 20-day moving average is widely watched 
      by short-term traders as a measure of the intermediate trend."
    """

    @property
    def name(self) -> str:
        return "Price > MA20"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.ma is None or context.ma.ma_20 is None:
            return False
        if context.current_price is None:
            return False
        return context.current_price > context.ma.ma_20


class PriceAboveMa60Rule(TradingRule):
    """
    Rule: Price must be above the 60-period Moving Average.
    
    Rationale:
    The 60-day (quarterly) MA represents the medium-term trend.
    Price above MA60 confirms the stock is in a sustained uptrend.
    
    Reference:
    - Murphy, J. (1999). "The 50-60 day moving average is considered
      the dividing line between the short and long-term trend."
    """

    @property
    def name(self) -> str:
        return "Price > MA60"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.ma is None or context.ma.ma_60 is None:
            return False
        if context.current_price is None:
            return False
        return context.current_price > context.ma.ma_60


class MaBullishAlignmentRule(TradingRule):
    """
    Rule: Moving averages must be in bullish alignment (MA20 > MA60).
    
    Rationale:
    When shorter-term MA is above longer-term MA, it indicates
    recent buying pressure is stronger than historical average.
    This is a classic trend-following signal.
    
    Reference:
    - Murphy, J. (1999). "When shorter-term averages cross above
      longer-term averages, it's bullish. When they cross below, it's bearish."
    """

    @property
    def name(self) -> str:
        return "MA20 > MA60 (Bullish Alignment)"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.ma is None:
            return False
        if context.ma.ma_20 is None or context.ma.ma_60 is None:
            return False
        return context.ma.ma_20 > context.ma.ma_60


class GoldenCrossRule(TradingRule):
    """
    Rule: MA20 recently crossed above MA60 (within lookback period).
    
    Rationale:
    The "Golden Cross" is one of the most reliable bullish signals.
    It indicates a shift from bearish to bullish momentum.
    
    Reference:
    - Murphy, J. (1999). "The golden cross occurs when a shorter-term
      moving average crosses above a longer-term moving average."
    - Bulkowski, T. (2005). Encyclopedia of Chart Patterns.
      "Golden crosses have a 70% success rate in bull markets."
    
    Note: This rule requires OHLCV history to detect the crossover.
    """

    def __init__(self, lookback_days: int = 5):
        """
        Args:
            lookback_days: Number of days to look back for the crossover.
        """
        self._lookback = lookback_days

    @property
    def name(self) -> str:
        return f"Golden Cross (within {self._lookback} days)"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        # This requires historical MA data which isn't in current model
        # For now, check if MA20 just crossed above MA60 (MA20 > MA60 and close)
        if context.ma is None:
            return False
        if context.ma.ma_20 is None or context.ma.ma_60 is None:
            return False
        
        ma_20 = float(context.ma.ma_20)
        ma_60 = float(context.ma.ma_60)
        
        # Check if MA20 is above MA60 but only by a small margin (recent cross)
        if ma_20 <= ma_60:
            return False
        
        # Recent cross: MA20 is above MA60 but by less than 3%
        cross_margin = (ma_20 - ma_60) / ma_60
        return 0 < cross_margin < 0.03


class AdxTrendStrengthRule(TradingRule):
    """
    Rule: ADX must indicate a trending market (not range-bound).
    
    Rationale:
    ADX measures trend strength regardless of direction.
    Only trade when there's a clear trend to follow.
    
    Interpretation:
    - ADX < 20: No trend (avoid trading)
    - ADX 20-40: Developing trend (good entry)
    - ADX > 40: Strong trend (may be late entry)
    
    Reference:
    - Wilder, J.W. (1978). New Concepts in Technical Trading Systems.
      "ADX is the ultimate trend strength indicator."
    """

    def __init__(self, min_adx: float = 20.0, max_adx: float = 50.0):
        self._min_adx = min_adx
        self._max_adx = max_adx

    @property
    def name(self) -> str:
        return f"ADX Trend ({self._min_adx}-{self._max_adx})"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if not hasattr(context, 'adx') or context.adx is None:
            # If ADX not available, pass the rule (don't block)
            return True
        if context.adx.adx is None:
            return True
        return self._min_adx <= context.adx.adx <= self._max_adx


class AdxBullishDirectionRule(TradingRule):
    """
    Rule: +DI must be greater than -DI (bullish direction).
    
    Rationale:
    +DI measures upward movement strength.
    -DI measures downward movement strength.
    For bullish trades, +DI should dominate.
    
    Reference:
    - Wilder, J.W. (1978). "When +DI is above -DI, bulls are in control."
    """

    @property
    def name(self) -> str:
        return "+DI > -DI (Bullish Direction)"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if not hasattr(context, 'adx') or context.adx is None:
            return True
        if context.adx.plus_di is None or context.adx.minus_di is None:
            return True
        return context.adx.plus_di > context.adx.minus_di


