"""
Technical Indicators Domain Models.

These are value objects that hold calculated indicator values.
    The calculation logic lives in the Infrastructure layer (IIndicatorProvider).
"""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Rsi:
    val_14: float | None
    val_7: float | None = None


@dataclass(frozen=True)
class Macd:
    line: float | None
    signal: float | None
    histogram: float | None = None


@dataclass(frozen=True)
class MovingAverages:
    ma_5: Decimal | None = None
    ma_10: Decimal | None = None
    ma_20: Decimal | None = None
    ma_60: Decimal | None = None
    ma_120: Decimal | None = None
    ema_12: Decimal | None = None
    ema_26: Decimal | None = None
    volume_ma_5: float | None = None
    volume_ma_20: float | None = None


@dataclass(frozen=True)
class BollingerBands:
    upper: Decimal | None
    middle: Decimal | None
    lower: Decimal | None
    bandwidth: float | None = None
    percent_b: float | None = None


@dataclass(frozen=True)
class Stochastic:
    k: float | None
    d: float | None


@dataclass(frozen=True)
class Adx:
    adx: float | None
    plus_di: float | None
    minus_di: float | None


@dataclass(frozen=True)
class Atr:
    atr_14: float | None
    atr_percent: float | None = None


@dataclass(frozen=True)
class Obv:
    obv: float | None
    obv_ma_20: float | None = None


@dataclass(frozen=True)
class Mfi:
    mfi_14: float | None


@dataclass(frozen=True)
class TechnicalIndicators:
    rsi: Rsi | None = None
    macd: Macd | None = None
    ma: MovingAverages | None = None
    bollinger: BollingerBands | None = None
    stochastic: Stochastic | None = None
    adx: Adx | None = None
    atr: Atr | None = None
    obv: Obv | None = None
    mfi: Mfi | None = None
