import math
from dataclasses import dataclass

from icontract import invariant


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
