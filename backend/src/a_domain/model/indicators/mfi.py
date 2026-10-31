import math
from dataclasses import dataclass

from icontract import invariant


@invariant(lambda self: self.period > 0)
@invariant(lambda self: math.isfinite(self.value))
@invariant(lambda self: 0 <= self.value <= 100)
@dataclass(frozen=True)
class Mfi:
    period: int
    value: float
