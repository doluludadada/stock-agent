from dataclasses import dataclass

import icontract

from a_domain.model.market.stock import Stock


@icontract.invariant(lambda self: self.max_daily_range_pct is None or self.max_daily_range_pct > 0)
@icontract.invariant(lambda self: self.min_atr_pct is None or self.min_atr_pct >= 0)
@icontract.invariant(lambda self: self.max_atr_pct is None or self.max_atr_pct > 0)
@icontract.invariant(lambda self: self.min_atr_pct is None or self.max_atr_pct is None or self.min_atr_pct <= self.max_atr_pct)
@dataclass(frozen=True)
class VolatilitySafetyCriterion:
    """
    Volatility safety condition.


    Daily range is a safety gate.
    ATR range is optional and can be used as a sizing / risk quality filter.
    """

    max_daily_range_pct: float | None = None
    min_atr_pct: float | None = None
    max_atr_pct: float | None = None
    require_atr: bool = False

    @property
    def name(self) -> str:
        checks: list[str] = []

        if self.max_daily_range_pct is not None:
            checks.append("daily range")

        if self.min_atr_pct is not None or self.max_atr_pct is not None:
            checks.append("ATR range")

        if not checks:
            return "Volatility Safety"

        return f"Volatility Safety ({', '.join(checks)})"

    def apply(self, stock: Stock) -> bool:
        if self.max_daily_range_pct is not None:
            if stock.today is None:
                return False

            if stock.today.low <= 0:
                return False

            daily_range = (stock.today.high - stock.today.low) / stock.today.low

            if daily_range >= self.max_daily_range_pct:
                return False

        if self.min_atr_pct is not None or self.max_atr_pct is not None:
            if stock.indicators is None or stock.indicators.atr is None:
                return not self.require_atr

            atr_percent = stock.indicators.atr.percent

            if self.min_atr_pct is not None and atr_percent < self.min_atr_pct:
                return False

            if self.max_atr_pct is not None and atr_percent > self.max_atr_pct:
                return False

        return True
