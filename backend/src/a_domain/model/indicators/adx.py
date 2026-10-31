from dataclasses import dataclass

from icontract import invariant


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
