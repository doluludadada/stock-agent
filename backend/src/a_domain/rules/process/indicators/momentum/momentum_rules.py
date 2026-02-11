"""
Momentum Rules.

Reference:
- Wilder, J.W. (1978). New Concepts in Technical Trading Systems.
- Appel, G. (2005). Technical Analysis: Power Tools for Active Investors.
- Elder, A. (1993). Trading for a Living.
"""
from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.analysis.stock_candidate import StockCandidate


class RsiRangeRule(TradingRule):
    """RSI must be within specified range."""

    def __init__(self, min_rsi: float = 0.0, max_rsi: float = 100.0):
        self._min_rsi = min_rsi
        self._max_rsi = max_rsi

    @property
    def name(self) -> str:
        return "RSI Range Check"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.rsi is None:
            return False
        if candidate.indicators.rsi.val_14 is None:
            return False
        return self._min_rsi <= candidate.indicators.rsi.val_14 <= self._max_rsi


class MacdCrossRule(TradingRule):
    """MACD Line must be above Signal Line."""

    @property
    def name(self) -> str:
        return "MACD Bullish Crossover"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.macd is None:
            return False
        macd = candidate.indicators.macd
        if macd.line is None or macd.signal is None:
            return False
        return macd.line > macd.signal


class MacdPositiveRule(TradingRule):
    """MACD Line must be positive (above zero line)."""

    @property
    def name(self) -> str:
        return "MACD Above Zero"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.macd is None:
            return False
        if candidate.indicators.macd.line is None:
            return False
        return candidate.indicators.macd.line > 0


class MacdHistogramRule(TradingRule):
    """MACD Histogram should be positive (momentum increasing)."""

    @property
    def name(self) -> str:
        return "MACD Histogram Rising"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.macd is None:
            return True
        if candidate.indicators.macd.histogram is None:
            return True
        return candidate.indicators.macd.histogram > 0


class StochasticThresholdRule(TradingRule):
    """Stochastic %K must not be overbought."""

    def __init__(self, threshold: float = 80.0):
        self._threshold = threshold

    @property
    def name(self) -> str:
        return "Stochastic Not Overbought"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.stochastic is None:
            return True
        if candidate.indicators.stochastic.k is None:
            return True
        return candidate.indicators.stochastic.k < self._threshold


class StochasticCrossRule(TradingRule):
    """Stochastic %K must be above %D (bullish crossover)."""

    @property
    def name(self) -> str:
        return "Stochastic Bullish Cross"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.stochastic is None:
            return True
        stoch = candidate.indicators.stochastic
        if stoch.k is None or stoch.d is None:
            return True
        return stoch.k > stoch.d


class MfiThresholdRule(TradingRule):
    """Money Flow Index must not be overbought."""

    def __init__(self, threshold: float = 80.0):
        self._threshold = threshold

    @property
    def name(self) -> str:
        return "MFI Not Overbought"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.mfi is None:
            return True
        if candidate.indicators.mfi.mfi_14 is None:
            return True
        return candidate.indicators.mfi.mfi_14 < self._threshold
