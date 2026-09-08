from dataclasses import dataclass

import icontract

from a_domain.model.market.stock import Stock

# TODO:
# ADD Comment


@icontract.invariant(lambda self: self.min_daily_volume >= 0)
@dataclass(frozen=True)
class LiquidityCriterion:
    min_daily_volume: int = 500

    @property
    def name(self) -> str:
        return "Liquidity Check"

    def apply(self, stock: Stock) -> bool:
        if not stock.ohlcv:
            return False

        recent_volumes = [bar.volume for bar in stock.ohlcv[-5:]]

        if not recent_volumes:
            return False

        average_volume = sum(recent_volumes) / len(recent_volumes)

        return average_volume >= self.min_daily_volume


@icontract.invariant(lambda self: self.min_price > 0)
@dataclass(frozen=True)
class MinimumPriceCriterion:
    min_price: float = 15.0

    @property
    def name(self) -> str:
        return "Minimum Price Check"

    def apply(self, stock: Stock) -> bool:
        if stock.current_price is None:
            return False

        return stock.current_price >= self.min_price


@icontract.invariant(lambda self: self.min_ratio > 0)
@icontract.invariant(lambda self: self.period > 0)
@dataclass(frozen=True)
class VolumeExpansionCriterion:
    min_ratio: float = 1.0
    period: int = 5

    @property
    def name(self) -> str:
        return f"Volume Expansion >= {self.min_ratio}x vs MA_{self.period}"

    def apply(self, stock: Stock) -> bool:
        moving_averages = stock.indicators.ma

        if moving_averages is None:
            return False

        average_volume = moving_averages.volume_ma.get(self.period)

        if average_volume is None:
            return False

        if not stock.ohlcv:
            return False

        current_volume = stock.current_volume

        if current_volume is None:
            return False

        return current_volume >= average_volume * self.min_ratio
        # TODO: Operator ">=" not supported for "None"PylancereportOptionalOperand


@dataclass(frozen=True)
class ObvTrendCriterion:
    @property
    def name(self) -> str:
        return "OBV Trend"

    def apply(self, stock: Stock) -> bool:
        obv = stock.indicators.obv

        if obv is None:
            return False

        return obv.value > obv.moving_average
