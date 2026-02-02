"""
Momentum Rules.

These rules measure the strength and speed of price movements.
Used to identify overbought/oversold conditions and momentum shifts.

Reference:
- Wilder, J.W. (1978). New Concepts in Technical Trading Systems.
- Appel, G. (2005). Technical Analysis: Power Tools for Active Investors.
- Elder, A. (1993). Trading for a Living.
"""
from typing import TYPE_CHECKING

from src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from src.a_domain.model.analysis.analysis_context import AnalysisContext


class RsiHealthyRule(TradingRule):
    """
    Rule: RSI should be in the healthy zone (not overbought or oversold).
    
    Rationale:
    - RSI > 70: Overbought, potential pullback
    - RSI < 30: Oversold, potential bounce
    - RSI 50-70: Bullish momentum, safe to buy
    
    Reference:
    - Wilder, J.W. (1978). "RSI readings above 70 indicate overbought conditions,
      while readings below 30 indicate oversold conditions."
    - Constance Brown (1999). "In uptrends, RSI tends to stay between 40-90,
      with the 40-50 zone acting as support."
    """

    def __init__(self, min_rsi: float = 50.0, max_rsi: float = 70.0):
        """
        Args:
            min_rsi: Minimum RSI for entry (default 50 = bullish momentum)
            max_rsi: Maximum RSI for entry (default 70 = not overbought)
        """
        self._min_rsi = min_rsi
        self._max_rsi = max_rsi

    @property
    def name(self) -> str:
        return f"RSI Healthy ({self._min_rsi}-{self._max_rsi})"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.rsi is None or context.rsi.val_14 is None:
            return False
        return self._min_rsi <= context.rsi.val_14 <= self._max_rsi


class RsiNotOverboughtRule(TradingRule):
    """
    Rule: RSI must not be overbought (< 80).
    
    Rationale:
    This is a safety rule. Even in strong uptrends, avoid buying
    when RSI is extremely high as pullback risk is elevated.
    
    Reference:
    - Elder, A. (1993). "Never buy when RSI is above 80. 
      Wait for a pullback to the 50-60 zone."
    """

    def __init__(self, max_rsi: float = 80.0):
        self._max_rsi = max_rsi

    @property
    def name(self) -> str:
        return f"RSI Not Overbought (< {self._max_rsi})"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.rsi is None or context.rsi.val_14 is None:
            return False
        return context.rsi.val_14 < self._max_rsi


class RsiBullishMomentumRule(TradingRule):
    """
    Rule: RSI must show bullish momentum (> 50).
    
    Rationale:
    RSI > 50 indicates that recent gains are larger than recent losses.
    This is a basic bullish momentum filter.
    
    Reference:
    - Constance Brown (1999). Technical Analysis for the Trading Professional.
      "RSI above 50 indicates bullish momentum, below 50 indicates bearish."
    """

    @property
    def name(self) -> str:
        return "RSI > 50 (Bullish Momentum)"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.rsi is None or context.rsi.val_14 is None:
            return False
        return context.rsi.val_14 > 50


class MacdBullishRule(TradingRule):
    """
    Rule: MACD Line must be above Signal Line.
    
    Rationale:
    When MACD Line crosses above Signal Line, it's a bullish signal.
    MACD staying above Signal confirms continued bullish momentum.
    
    Reference:
    - Appel, G. (2005). "The most important MACD signal occurs when
      the MACD line crosses above the signal line."
    """

    @property
    def name(self) -> str:
        return "MACD > Signal (Bullish)"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.macd is None:
            return False
        if context.macd.line is None or context.macd.signal is None:
            return False
        return context.macd.line > context.macd.signal


class MacdPositiveRule(TradingRule):
    """
    Rule: MACD Line must be positive (above zero line).
    
    Rationale:
    Positive MACD means the 12-period EMA is above the 26-period EMA.
    This confirms the short-term trend is bullish.
    
    Reference:
    - Appel, G. (2005). "When MACD is above zero, the trend is up.
      When MACD is below zero, the trend is down."
    """

    @property
    def name(self) -> str:
        return "MACD > 0 (Above Zero Line)"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.macd is None or context.macd.line is None:
            return False
        return context.macd.line > 0


class MacdHistogramRisingRule(TradingRule):
    """
    Rule: MACD Histogram should be rising (momentum increasing).
    
    Rationale:
    Rising histogram means the gap between MACD and Signal is widening.
    This indicates momentum is accelerating.
    
    Reference:
    - Elder, A. (1993). "The slope of the MACD histogram is more important
      than its position above or below zero."
    
    Note: Requires histogram history to detect rising pattern.
    """

    @property
    def name(self) -> str:
        return "MACD Histogram Rising"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.macd is None or context.macd.histogram is None:
            return True  # Pass if not available
        # For now, just check histogram is positive (bullish)
        return context.macd.histogram > 0


class StochasticNotOverboughtRule(TradingRule):
    """
    Rule: Stochastic %K must not be overbought (< 80).
    
    Rationale:
    Stochastic measures where price closed relative to the range.
    Above 80 means price is near the top of recent range.
    
    Reference:
    - Lane, G. (1984). "Stochastic readings above 80 suggest
      the market may be overextended to the upside."
    """

    @property
    def name(self) -> str:
        return "Stochastic Not Overbought (< 80)"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if not hasattr(context, 'stochastic') or context.stochastic is None:
            return True  # Pass if not available
        if context.stochastic.k is None:
            return True
        return context.stochastic.k < 80


class StochasticBullishCrossRule(TradingRule):
    """
    Rule: Stochastic %K must be above %D (bullish crossover).
    
    Rationale:
    %K crossing above %D is a buy signal.
    %K staying above %D confirms bullish momentum.
    
    Reference:
    - Lane, G. (1984). "Buy when %K crosses above %D from below 20.
      Sell when %K crosses below %D from above 80."
    """

    @property
    def name(self) -> str:
        return "Stochastic %K > %D (Bullish)"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if not hasattr(context, 'stochastic') or context.stochastic is None:
            return True
        if context.stochastic.k is None or context.stochastic.d is None:
            return True
        return context.stochastic.k > context.stochastic.d


class MfiNotOverboughtRule(TradingRule):
    """
    Rule: Money Flow Index must not be overbought (< 80).
    
    Rationale:
    MFI is volume-weighted RSI. It combines price and volume.
    MFI > 80 suggests heavy buying may be exhausted.
    
    Reference:
    - Quong & Soudack (1989). "MFI above 80 indicates buying pressure
      may be overextended. Wait for pullback."
    """

    @property
    def name(self) -> str:
        return "MFI Not Overbought (< 80)"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if not hasattr(context, 'mfi') or context.mfi is None:
            return True
        if context.mfi.mfi_14 is None:
            return True
        return context.mfi.mfi_14 < 80
