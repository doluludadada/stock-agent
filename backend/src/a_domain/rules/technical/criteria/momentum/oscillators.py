from dataclasses import dataclass

import icontract

from a_domain.model.market.stock import Stock


@icontract.invariant(lambda self: 0 <= self.min_rsi <= self.max_rsi <= 100)
@dataclass(frozen=True)
class RsiRangeCriterion:
    min_rsi: float = 0.0
    max_rsi: float = 100.0
    allow_missing: bool = False

    @property
    def name(self) -> str:
        return f"RSI Range {self.min_rsi}-{self.max_rsi}"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.rsi is None:
            return self.allow_missing

        return self.min_rsi <= stock.indicators.rsi.value <= self.max_rsi


@icontract.invariant(lambda self: 0 <= self.max_mfi <= 100)
@dataclass(frozen=True)
class MfiThresholdCriterion:
    max_mfi: float = 80.0
    allow_missing: bool = True

    @property
    def name(self) -> str:
        return f"MFI < {self.max_mfi}"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.mfi is None:
            return self.allow_missing

        return stock.indicators.mfi.value < self.max_mfi
