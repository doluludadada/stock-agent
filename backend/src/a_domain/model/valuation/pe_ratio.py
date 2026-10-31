from __future__ import annotations

import math
from dataclasses import dataclass

from icontract import invariant


@invariant(lambda self: math.isfinite(self.price) and self.price > 0)
@invariant(lambda self: math.isfinite(self.eps) and self.eps > 0)
@dataclass(frozen=True)
class PeRatio:
    """A computable P/E. Holding a positive price and EPS makes it the only input a fair price accepts."""

    price: float
    eps: float

    @property
    def value(self) -> float:
        return self.price / self.eps
