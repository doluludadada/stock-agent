from dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.types.enums import MaPeriod


# TODO:Add comment
# TODO: delete MaPeriod?
def get_ma_value(stock: Stock, period: MaPeriod) -> float | None:
    if stock.indicators is None or stock.indicators.ma is None:
        return None

    ma = stock.indicators.ma

    return {
        MaPeriod.MA_5: ma.ma_5,
        MaPeriod.MA_10: ma.ma_10,
        MaPeriod.MA_20: ma.ma_20,
        MaPeriod.MA_60: ma.ma_60,
        MaPeriod.MA_120: ma.ma_120,
    }.get(period)


@dataclass(frozen=True)
class PriceAboveMaCriterion:
    ma_period: MaPeriod

    @property
    def name(self) -> str:
        return f"Price Above {self.ma_period.value}"

    def apply(self, stock: Stock) -> bool:
        ma_value = get_ma_value(stock, self.ma_period)

        if ma_value is None or stock.current_price is None:
            return False

        return stock.current_price > ma_value


@dataclass(frozen=True)
class MaAlignmentCriterion:
    fast: MaPeriod = MaPeriod.MA_20
    slow: MaPeriod = MaPeriod.MA_60

    @property
    def name(self) -> str:
        return f"{self.fast.value} > {self.slow.value} Alignment"

    def apply(self, stock: Stock) -> bool:
        fast_value = get_ma_value(stock, self.fast)
        slow_value = get_ma_value(stock, self.slow)

        if fast_value is None or slow_value is None:
            return False

        return fast_value > slow_value


@dataclass(frozen=True)
class GoldenCrossCriterion:
    max_cross_margin: float = 0.03

    @property
    def name(self) -> str:
        return "Golden Cross"

    def apply(self, stock: Stock) -> bool:
        ma20 = get_ma_value(stock, MaPeriod.MA_20)
        ma60 = get_ma_value(stock, MaPeriod.MA_60)

        if ma20 is None or ma60 is None:
            return False

        if ma60 <= 0:
            return False

        if ma20 <= ma60:
            return False

        cross_margin = (ma20 - ma60) / ma60

        return 0 < cross_margin < self.max_cross_margin
