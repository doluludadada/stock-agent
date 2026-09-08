from dataclasses import dataclass

import icontract

from a_domain.model.market.stock import Stock


@icontract.invariant(lambda self: self.max_daily_range_pct > 0)
@dataclass(frozen=True)
class DailyRangeCriterion:
    """
    Volatility safety condition.


    Daily range is a safety gate.
    """

    max_daily_range_pct: float

    @property
    def name(self) -> str:
        return "Daily Range Safety"

    # TODO: Function with declared return type "bool" must return value on all code paths
    #   "None" is not assignable to "bool"
    def apply(self, stock: Stock) -> bool:
        if stock.today is None or stock.today.low <= 0:
            return False

        daily_range = (stock.today.high - stock.today.low) / stock.today.low

        return daily_range < self.max_daily_range_pct


@icontract.invariant(lambda self: self.min_atr_pct is None or self.min_atr_pct >= 0)
@icontract.invariant(lambda self: self.max_atr_pct is None or self.max_atr_pct > 0)
@icontract.invariant(lambda self: self.min_atr_pct is not None or self.max_atr_pct is not None)
@icontract.invariant(lambda self: self.min_atr_pct is None or self.max_atr_pct is None or self.min_atr_pct <= self.max_atr_pct)
@dataclass(frozen=True)
class AtrRangeCriterion:
    """
    ATR range is optional and can be used as a sizing / risk quality filter.
    """

    min_atr_pct: float | None = None
    max_atr_pct: float | None = None

    @property
    def name(self) -> str:
        return "ATR Range"

    def apply(self, stock: Stock) -> bool:
        atr = stock.indicators.atr

        if atr is None:
            return False

        if self.min_atr_pct is not None and atr.percent < self.min_atr_pct:
            return False

        return self.max_atr_pct is None or atr.percent <= self.max_atr_pct
