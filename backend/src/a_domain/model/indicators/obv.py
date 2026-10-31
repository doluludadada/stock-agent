import math
from dataclasses import dataclass

from icontract import invariant


@invariant(lambda self: self.ma_period > 0)
@invariant(lambda self: math.isfinite(self.value))
@invariant(lambda self: math.isfinite(self.moving_average))
@dataclass(frozen=True)
class Obv:
    ma_period: int
    value: float
    moving_average: float
