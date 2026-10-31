import math
from dataclasses import dataclass

from icontract import invariant


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
