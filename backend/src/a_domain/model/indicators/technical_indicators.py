"""
Technical Indicators Domain Models.

Value objects holding calculated indicator values.
Calculation logic lives in the Infrastructure layer (IIndicatorProvider).
All values use float for consistency (these are calculated values, not currency).
"""
import math
from dataclasses import dataclass, field

from icontract import invariant


@invariant(lambda self: self.val_14 is None or 0 <= self.val_14 <= 100)
@invariant(lambda self: self.val_7 is None or 0 <= self.val_7 <= 100)
@dataclass(frozen=True)
class Rsi:
    val_14: float | None
    val_7: float | None = None


@dataclass(frozen=True)
class Macd:
    line: float | None
    signal: float | None
    histogram: float | None = None


@invariant(lambda self: all(k > 0 and math.isfinite(v) and v > 0 for k, v in self.price_ma.items()))
@invariant(lambda self: all(k > 0 and math.isfinite(v) and v > 0 for k, v in self.volume_ma.items()))
@dataclass(frozen=True)
class MovingAverages:
    price_ma: dict[int, float] = field(default_factory=dict)
    volume_ma: dict[int, float] = field(default_factory=dict)


@invariant(
    lambda self: (self.upper is None or self.lower is None) or self.upper >= self.lower,
    "Bollinger upper must be >= lower"
)
@dataclass(frozen=True)
class BollingerBands:
    upper: float | None
    middle: float | None
    lower: float | None
    bandwidth: float | None = None
    percent_b: float | None = None


@invariant(lambda self: self.k is None or 0 <= self.k <= 100)
@invariant(lambda self: self.d is None or 0 <= self.d <= 100)
@dataclass(frozen=True)
class Stochastic:
    k: float | None
    d: float | None


@invariant(lambda self: self.adx is None or 0 <= self.adx <= 100)
@invariant(lambda self: self.plus_di is None or self.plus_di >= 0)
@invariant(lambda self: self.minus_di is None or self.minus_di >= 0)
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


@invariant(lambda self: self.mfi_14 is None or 0 <= self.mfi_14 <= 100)
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
