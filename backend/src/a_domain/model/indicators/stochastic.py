from dataclasses import dataclass

from icontract import invariant


@invariant(lambda self: self.k_period > 0)
@invariant(lambda self: self.d_period > 0)
@invariant(lambda self: 0 <= self.percent_k <= 100)
@invariant(lambda self: 0 <= self.percent_d <= 100)
@dataclass(frozen=True)
class Stochastic:
    k_period: int
    d_period: int
    percent_k: float
    percent_d: float
