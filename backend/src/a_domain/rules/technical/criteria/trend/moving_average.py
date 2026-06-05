from dataclasses import dataclass

import icontract

from a_domain.model.market.stock import Stock


@icontract.invariant(lambda self: self.period > 0)
@dataclass(frozen=True)
class PriceAboveMaCriterion:
    period: int

    @property
    def name(self) -> str:
        return f"Price Above MA_{self.period}"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.ma is None:
            return False

        if stock.current_price is None:
            return False

        price_ma = stock.indicators.ma.price_ma.get(self.period)

        return price_ma is not None and stock.current_price > price_ma


@icontract.invariant(lambda self: self.fast > 0)
@icontract.invariant(lambda self: self.slow > 0)
@icontract.invariant(lambda self: self.fast != self.slow)
@dataclass(frozen=True)
class MaAlignmentCriterion:
    fast: int = 20
    slow: int = 60

    @property
    def name(self) -> str:
        return f"MA_{self.fast} > MA_{self.slow} Alignment"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.ma is None:
            return False

        ma = stock.indicators.ma
        fast_value = ma.price_ma.get(self.fast)
        slow_value = ma.price_ma.get(self.slow)

        return fast_value is not None and slow_value is not None and fast_value > slow_value


@icontract.invariant(lambda self: self.fast > 0)
@icontract.invariant(lambda self: self.slow > 0)
@icontract.invariant(lambda self: self.fast != self.slow)
@icontract.invariant(lambda self: self.max_cross_margin > 0)
@dataclass(frozen=True)
class GoldenCrossCriterion:
    fast: int = 20
    slow: int = 60
    max_cross_margin: float = 0.03

    @property
    def name(self) -> str:
        return "Golden Cross"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.ma is None:
            return False

        ma = stock.indicators.ma
        fast_value = ma.price_ma.get(self.fast)
        slow_value = ma.price_ma.get(self.slow)

        if fast_value is None or slow_value is None:
            return False

        if fast_value <= slow_value:
            return False

        cross_margin = (fast_value - slow_value) / slow_value

        return 0 < cross_margin < self.max_cross_margin
