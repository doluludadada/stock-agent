from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class MovingAverages:
    """
    Moving Averages (Simple, Exponential checks) Domain Model.
    """
    ma_20: Decimal | None
    ma_60: Decimal | None
    volume_ma_5: float | None
