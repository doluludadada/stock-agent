from dataclasses import dataclass

import icontract

from a_domain.model.market.stock import Stock


@icontract.invariant(lambda self: 0 <= self.min_adx <= self.max_adx <= 100)
@dataclass(frozen=True)
class AdxTrendCriterion:
    """
    ADX trend health criterion.

    Checks:
    1. ADX is inside an acceptable trend-strength range.
    2. Optionally, +DI must be greater than -DI.

    """

    min_adx: float = 20.0
    max_adx: float = 50.0
    require_direction: bool = True
    allow_missing: bool = True

    @property
    def name(self) -> str:
        if self.require_direction:
            return f"ADX Trend {self.min_adx}-{self.max_adx} with Bullish Direction"

        return f"ADX Trend {self.min_adx}-{self.max_adx}"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.adx is None:
            return self.allow_missing

        adx = stock.indicators.adx

        if adx.adx is None:
            return self.allow_missing

        if not self.min_adx <= adx.adx <= self.max_adx:
            return False

        if not self.require_direction:
            return True

        if adx.plus_di is None or adx.minus_di is None:
            return self.allow_missing

        return adx.plus_di > adx.minus_di
