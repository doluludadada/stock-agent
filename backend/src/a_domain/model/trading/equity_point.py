from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class EquityPoint:
    day: date
    cash: float
    market_value: float

    @property
    def equity(self) -> float:
        return self.cash + self.market_value
