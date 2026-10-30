from dataclasses import dataclass

import icontract

from a_domain.model.market.stock import Stock


@icontract.invariant(lambda self: self.min_daily_volume >= 0)
@dataclass(frozen=True)
class LiquidityCriterion:
    """
    Passes when the average volume of the latest five daily bars reaches `min_daily_volume`.

    Volume is in shares, as the OHLCV provider reports it, not in 1,000-share lots.
    """

    min_daily_volume: int = 500

    @property
    def name(self) -> str:
        return "Liquidity Check"

    def apply(self, stock: Stock) -> bool:
        if not stock.ohlcv:
            return False

        recent_volumes = [bar.volume for bar in stock.ohlcv[-5:]]
        average_volume = sum(recent_volumes) / len(recent_volumes)

        return average_volume >= self.min_daily_volume


@icontract.invariant(lambda self: self.min_price > 0)
@dataclass(frozen=True)
class MinimumPriceCriterion:
    """Passes when the current price, realtime when available, is at least `min_price`."""

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
    """
    Passes when the latest daily volume is at least `min_ratio` times its `period`-day average.

    A ratio below 1 is a dry-volume floor; a ratio above 1 asks for expansion.
    """

    min_ratio: float = 1.0
    period: int = 5

    @property
    def name(self) -> str:
        return f"Volume Expansion >= {self.min_ratio}x vs MA_{self.period}"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators.ma is None or stock.current_volume is None:
            return False

        average_volume = stock.indicators.ma.volume_ma.get(self.period)

        if average_volume is None:
            return False

        return stock.current_volume >= average_volume * self.min_ratio


@dataclass(frozen=True)
class ObvTrendCriterion:
    """Passes when on-balance volume is above its moving average, meaning volume has favoured up days."""

    @property
    def name(self) -> str:
        return "OBV Trend"

    def apply(self, stock: Stock) -> bool:
        obv = stock.indicators.obv

        if obv is None:
            return False

        return obv.value > obv.moving_average
