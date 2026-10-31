from dataclasses import dataclass
from typing import override

import icontract

from a_domain.model.market.stock import Stock


@icontract.invariant(lambda self: self.max_drop_pct >= 0)
@dataclass(frozen=True)
class PriceDropCriterion:
    """Passes unless the latest close fell more than `max_drop_pct` from the previous close."""

    max_drop_pct: float = 0.03

    @override
    def __str__(self) -> str:
        return "Price Drop Check"

    def apply(self, stock: Stock) -> bool:
        if stock.today is None or stock.yesterday is None:
            return False

        if stock.yesterday.close == 0:
            return False

        change = (stock.today.close - stock.yesterday.close) / stock.yesterday.close

        return change > -self.max_drop_pct


@icontract.invariant(lambda self: self.max_gap_pct >= 0)
@dataclass(frozen=True)
class GapCriterion:
    """Passes unless the latest open gapped up `max_gap_pct` or more above the previous close."""

    max_gap_pct: float = 0.03

    @override
    def __str__(self) -> str:
        return "Gap Check"

    def apply(self, stock: Stock) -> bool:
        if stock.today is None or stock.yesterday is None:
            return False

        if stock.yesterday.close == 0:
            return False

        gap = (stock.today.open - stock.yesterday.close) / stock.yesterday.close

        return gap < self.max_gap_pct


@dataclass(frozen=True)
class IntradayMomentumCriterion:
    """Passes when the latest daily bar closed above its open."""

    @override
    def __str__(self) -> str:
        return "Intraday Momentum"

    def apply(self, stock: Stock) -> bool:
        if stock.today is None:
            return False

        if stock.today.open <= 0:
            return False

        return stock.today.close > stock.today.open


@icontract.invariant(lambda self: 0 <= self.max_range_position <= 1)
@dataclass(frozen=True)
class IntradayRangeCriterion:
    """
    Passes when the latest close sits below `max_range_position` of the day's low-to-high range.

    0 is the low and 1 is the high, so the check avoids entries at the top of the day.
    """

    max_range_position: float = 0.8

    @override
    def __str__(self) -> str:
        return "Intraday Range Position"

    def apply(self, stock: Stock) -> bool:
        if stock.today is None:
            return False

        spread = stock.today.high - stock.today.low

        if spread <= 0:
            return False

        position = (stock.today.close - stock.today.low) / spread

        return position < self.max_range_position


@icontract.invariant(lambda self: self.max_consecutive_up > 0)
@dataclass(frozen=True)
class ConsecutiveUpDaysCriterion:
    """Passes when the stock has closed higher on fewer than `max_consecutive_up` consecutive days."""

    max_consecutive_up: int = 4

    @override
    def __str__(self) -> str:
        return "Consecutive Up Days Check"

    def apply(self, stock: Stock) -> bool:
        bars = stock.ohlcv

        if len(bars) < self.max_consecutive_up + 1:
            return False

        count = 0

        for i in range(len(bars) - 1, 0, -1):
            if bars[i].close > bars[i - 1].close:
                count += 1
            else:
                break

        return count < self.max_consecutive_up
