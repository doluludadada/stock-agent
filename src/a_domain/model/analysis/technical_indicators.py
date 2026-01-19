from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TechnicalIndicators:
    """
    Standardized container for technical values calculated by Infrastructure.
    """

    rsi_14: float | None
    macd_line: float | None
    macd_signal: float | None
    ma_20: Decimal | None
    ma_60: Decimal | None
    volume_ma_5: float | None
