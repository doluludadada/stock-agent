import math
from dataclasses import dataclass, field

from icontract import invariant


@invariant(lambda self: all(period > 0 and math.isfinite(value) and value > 0 for period, value in self.price_ma.items()))
@invariant(lambda self: all(period > 0 and math.isfinite(value) and value > 0 for period, value in self.volume_ma.items()))
@dataclass(frozen=True)
class MovingAverages:
    price_ma: dict[int, float] = field(default_factory=dict)
    volume_ma: dict[int, float] = field(default_factory=dict)
