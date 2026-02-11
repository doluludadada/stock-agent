"""
Trend Following Rules.

Reference:
- Murphy, J. (1999). Technical Analysis of the Financial Markets, Chapter 9.
- Elder, A. (1993). Trading for a Living, Chapter 5.
"""

from decimal import Decimal

from backend.src.a_domain.model.analysis.stock_candidate import StockCandidate
from backend.src.a_domain.model.indicators.technical_indicators import MovingAverages
from backend.src.a_domain.rules.base import TradingRule
from backend.src.a_domain.types.enums import MaPeriod


class PriceAboveMaRule(TradingRule):
    """Price must be above the specified Moving Average."""

    def __init__(self, ma_period: MaPeriod):
        self._ma_period = ma_period

    @property
    def name(self) -> str:
        return f"Price Above {self._ma_period.value}"

    def _get_ma_value(self, ma: MovingAverages) -> Decimal | None:
        match self._ma_period:
            case MaPeriod.MA_5:
                return ma.ma_5
            case MaPeriod.MA_10:
                return ma.ma_10
            case MaPeriod.MA_20:
                return ma.ma_20
            case MaPeriod.MA_60:
                return ma.ma_60
            case MaPeriod.MA_120:
                return ma.ma_120
            case _:
                return None

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.ma is None:
            return False
        ma_value = self._get_ma_value(candidate.indicators.ma)
        if ma_value is None or candidate.current_price is None:
            return False
        return candidate.current_price > ma_value


class MaAlignmentRule(TradingRule):
    """Fast MA must be above slow MA (bullish alignment)."""

    def __init__(self, fast: MaPeriod = MaPeriod.MA_20, slow: MaPeriod = MaPeriod.MA_60):
        self._fast = fast
        self._slow = slow

    @property
    def name(self) -> str:
        return f"{self._fast.value} > {self._slow.value} Alignment"

    def _get_ma_value(self, ma: MovingAverages, period: MaPeriod) -> Decimal | None:
        match period:
            case MaPeriod.MA_5:
                return ma.ma_5
            case MaPeriod.MA_10:
                return ma.ma_10
            case MaPeriod.MA_20:
                return ma.ma_20
            case MaPeriod.MA_60:
                return ma.ma_60
            case MaPeriod.MA_120:
                return ma.ma_120
            case _:
                return None

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.ma is None:
            return False
        ma = candidate.indicators.ma
        fast_val = self._get_ma_value(ma, self._fast)
        slow_val = self._get_ma_value(ma, self._slow)
        if fast_val is None or slow_val is None:
            return False
        return fast_val > slow_val


class GoldenCrossRule(TradingRule):
    """MA20 recently crossed above MA60 (within margin)."""

    def __init__(self, max_cross_margin: float = 0.03):
        self._max_cross_margin = max_cross_margin

    @property
    def name(self) -> str:
        return "Golden Cross"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.ma is None:
            return False

        ma = candidate.indicators.ma
        if ma.ma_20 is None or ma.ma_60 is None:
            return False

        ma_20 = float(ma.ma_20)
        ma_60 = float(ma.ma_60)

        if ma_20 <= ma_60:
            return False

        cross_margin = (ma_20 - ma_60) / ma_60
        return 0 < cross_margin < self._max_cross_margin


class AdxTrendStrengthRule(TradingRule):
    """ADX must indicate a trending market (not range-bound, not exhausted)."""

    def __init__(self, min_adx: float = 20.0, max_adx: float = 50.0):
        self._min_adx = min_adx
        self._max_adx = max_adx

    @property
    def name(self) -> str:
        return "ADX Trend Strength"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.adx is None:
            return True
        if candidate.indicators.adx.adx is None:
            return True
        return self._min_adx <= candidate.indicators.adx.adx <= self._max_adx


class AdxDirectionRule(TradingRule):
    """+DI must be greater than -DI (bullish direction)."""

    @property
    def name(self) -> str:
        return "ADX Bullish Direction"

    def is_satisfied(self, candidate: "StockCandidate") -> bool:
        if candidate.indicators is None or candidate.indicators.adx is None:
            return True
        adx = candidate.indicators.adx
        if adx.plus_di is None or adx.minus_di is None:
            return True
        return adx.plus_di > adx.minus_di
