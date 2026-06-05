from dataclasses import dataclass

import icontract

from a_domain.model.market.stock import Stock


# TODO: Add comment
@icontract.invariant(lambda self: self.max_drop_pct >= 0)
@dataclass(frozen=True)
class PriceDropCriterion:
    max_drop_pct: float = 0.03

    @property
    def name(self) -> str:
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
    max_gap_pct: float = 0.03

    @property
    def name(self) -> str:
        return "Gap Check"

    def apply(self, stock: Stock) -> bool:
        if stock.today is None or stock.yesterday is None:
            return True

        if stock.yesterday.close == 0:
            return True

        gap = (stock.today.open - stock.yesterday.close) / stock.yesterday.close

        return gap < self.max_gap_pct


@dataclass(frozen=True)
class IntradayMomentumCriterion:
    @property
    def name(self) -> str:
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
    max_range_position: float = 0.8

    @property
    def name(self) -> str:
        return "Intraday Range Position"

    def apply(self, stock: Stock) -> bool:
        if stock.today is None:
            return True

        spread = stock.today.high - stock.today.low

        if spread <= 0:
            return True

        position = (stock.today.close - stock.today.low) / spread

        return position < self.max_range_position


@icontract.invariant(lambda self: self.min_volume_ratio >= 0)
@icontract.invariant(lambda self: self.period > 0)
@dataclass(frozen=True)
class IntradayVolumeConfirmationCriterion:
    min_volume_ratio: float = 0.5
    period: int = 5

    @property
    def name(self) -> str:
        return f"Intraday Volume Confirmation vs MA_{self.period}"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.ma is None:
            return True

        average_volume = stock.indicators.ma.volume_ma.get(self.period)

        if average_volume is None:
            return True

        if not stock.ohlcv:
            return False

        today_volume = stock.ohlcv[-1].volume

        return today_volume >= average_volume * self.min_volume_ratio


@icontract.invariant(lambda self: self.max_consecutive_up > 0)
@dataclass(frozen=True)
class ConsecutiveUpDaysCriterion:
    max_consecutive_up: int = 4

    @property
    def name(self) -> str:
        return "Consecutive Up Days Check"

    def apply(self, stock: Stock) -> bool:
        bars = stock.ohlcv

        if len(bars) < self.max_consecutive_up + 1:
            return True

        count = 0

        for i in range(len(bars) - 1, 0, -1):
            if bars[i].close > bars[i - 1].close:
                count += 1
            else:
                break

        return count < self.max_consecutive_up
