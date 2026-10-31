import math
from dataclasses import dataclass

from icontract import invariant


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
