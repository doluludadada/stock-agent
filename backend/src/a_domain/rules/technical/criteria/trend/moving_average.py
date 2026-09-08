# backend/src/a_domain/rules/technical/criteria/trend/moving_average.py

from dataclasses import dataclass

import icontract

from a_domain.model.market.stock import Stock
from a_domain.rules.technical.calculation.formulas import latest_sma


@icontract.invariant(lambda self: self.period > 0)
@dataclass(frozen=True)
class PriceAboveMaCriterion:
    period: int

    @property
    def name(self) -> str:
        return f"Price Above MA_{self.period}"

    def apply(self, stock: Stock) -> bool:
        moving_averages = stock.indicators.ma

        if moving_averages is None or stock.current_price is None:
            return False

        average_price = moving_averages.price_ma.get(self.period)

        return average_price is not None and stock.current_price > average_price


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
        moving_averages = stock.indicators.ma

        if moving_averages is None:
            return False

        fast_value = moving_averages.price_ma.get(self.fast)
        slow_value = moving_averages.price_ma.get(self.slow)

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
        moving_averages = stock.indicators.ma
        if moving_averages is None:
            return False

        current_fast = moving_averages.price_ma.get(self.fast)
        current_slow = moving_averages.price_ma.get(self.slow)
        if current_fast is None or current_slow is None or current_slow <= 0:
            return False

        bars = sorted(stock.ohlcv, key=lambda bar: bar.ts)
        previous_closes = [bar.close for bar in bars[:-1]]

        previous_fast = latest_sma(previous_closes, self.fast)
        previous_slow = latest_sma(previous_closes, self.slow)
        if previous_fast is None or previous_slow is None:
            return False

        crossed_up = previous_fast <= previous_slow and current_fast > current_slow
        if not crossed_up:
            return False

        cross_margin = (current_fast - current_slow) / current_slow
        return cross_margin < self.max_cross_margin
