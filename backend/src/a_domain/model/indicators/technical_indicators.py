"""
Technical Indicators Domain Models.

Value objects holding calculated indicator values.

If an indicator object exists, its calculated values are present. Missing or
insufficient history is represented by omitting the indicator object from
TechnicalIndicators.
"""

import math
from dataclasses import dataclass, field

from icontract import invariant


@invariant(lambda self: self.period > 0)
@invariant(lambda self: math.isfinite(self.value))
@invariant(lambda self: 0 <= self.value <= 100)
@dataclass(frozen=True)
class Rsi:
    period: int
    value: float


@invariant(lambda self: self.fast > 0)
@invariant(lambda self: self.slow > 0)
@invariant(lambda self: self.signal_period > 0)
@invariant(lambda self: self.fast != self.slow)
@invariant(lambda self: math.isfinite(self.line))
@invariant(lambda self: math.isfinite(self.signal))
@invariant(lambda self: math.isfinite(self.histogram))
@dataclass(frozen=True)
class Macd:
    fast: int
    slow: int
    signal_period: int
    line: float
    signal: float
    histogram: float


@invariant(lambda self: all(k > 0 and math.isfinite(v) and v > 0 for k, v in self.price_ma.items()))
@invariant(lambda self: all(k > 0 and math.isfinite(v) and v > 0 for k, v in self.volume_ma.items()))
@dataclass(frozen=True)
class MovingAverages:
    price_ma: dict[int, float] = field(default_factory=dict)
    volume_ma: dict[int, float] = field(default_factory=dict)


@invariant(lambda self: self.period > 0)
@invariant(lambda self: self.std > 0)
@invariant(lambda self: math.isfinite(self.upper))
@invariant(lambda self: math.isfinite(self.middle))
@invariant(lambda self: math.isfinite(self.lower))
@invariant(lambda self: math.isfinite(self.bandwidth))
@invariant(lambda self: math.isfinite(self.percent_b))
@invariant(lambda self: self.upper >= self.lower, "Bollinger upper must be >= lower")
@dataclass(frozen=True)
class BollingerBands:
    period: int
    std: float
    upper: float
    middle: float
    lower: float
    bandwidth: float
    percent_b: float


@invariant(lambda self: self.k_period > 0)
@invariant(lambda self: self.d_period > 0)
@invariant(lambda self: 0 <= self.k <= 100)
@invariant(lambda self: 0 <= self.d <= 100)
@dataclass(frozen=True)
class Stochastic:
    k_period: int
    d_period: int
    k: float
    d: float


@invariant(lambda self: self.period > 0)
@invariant(lambda self: 0 <= self.adx <= 100)
@invariant(lambda self: self.plus_di >= 0)
@invariant(lambda self: self.minus_di >= 0)
@dataclass(frozen=True)
class Adx:
    period: int
    adx: float
    plus_di: float
    minus_di: float


@invariant(lambda self: self.period > 0)
@invariant(lambda self: math.isfinite(self.value))
@invariant(lambda self: self.value >= 0)
@invariant(lambda self: math.isfinite(self.percent))
@invariant(lambda self: self.percent >= 0)
@dataclass(frozen=True)
class Atr:
    period: int
    value: float
    percent: float


@invariant(lambda self: self.ma_period > 0)
@invariant(lambda self: math.isfinite(self.value))
@invariant(lambda self: math.isfinite(self.moving_average))
@dataclass(frozen=True)
class Obv:
    ma_period: int
    value: float
    moving_average: float


@invariant(lambda self: self.period > 0)
@invariant(lambda self: math.isfinite(self.value))
@invariant(lambda self: 0 <= self.value <= 100)
@dataclass(frozen=True)
class Mfi:
    period: int
    value: float


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
