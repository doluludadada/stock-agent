from dataclasses import replace
from typing import Self

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class MarketValuation:
    prices: dict[str, float]


@dataclass(frozen=True)
class ValuationScan:
    survivors: tuple[str, ...]

    def after_technical_step(self, passed: frozenset[str]) -> Self:
        return replace(self, survivors=tuple(stock_id for stock_id in self.survivors if stock_id in passed))
