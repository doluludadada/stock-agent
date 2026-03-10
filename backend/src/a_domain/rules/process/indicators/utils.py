"""Shared utilities for indicator rules."""

from a_domain.model.indicators.technical_indicators import MovingAverages
from a_domain.types.enums import MaPeriod


def get_ma_value(ma: MovingAverages, period: MaPeriod) -> float | None:
    """Look up a moving average value by period. Used by PriceAboveMaRule and MaAlignmentRule."""
    return {
        MaPeriod.MA_5: ma.ma_5,
        MaPeriod.MA_10: ma.ma_10,
        MaPeriod.MA_20: ma.ma_20,
        MaPeriod.MA_60: ma.ma_60,
        MaPeriod.MA_120: ma.ma_120,
    }.get(period)
