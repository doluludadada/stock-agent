from dataclasses import dataclass

import icontract

from a_domain.model.market.stock import Stock


@dataclass(frozen=True)
class BollingerPositionCriterion:
    """Passes when the current price is above the middle band, the band's moving average."""

    @property
    def name(self) -> str:
        return "Bollinger Above Middle"

    def apply(self, stock: Stock) -> bool:
        bollinger = stock.indicators.bollinger

        if bollinger is None or stock.current_price is None:
            return False

        return stock.current_price > bollinger.middle


@icontract.invariant(lambda self: self.max_percent_b > 0)
@dataclass(frozen=True)
class BollingerThresholdCriterion:
    """
    Passes when %B is below `max_percent_b`.

    %B is 0 at the lower band and 1 at the upper band, so a limit near 1 rejects a close
    that is already stretched against the upper band.
    """

    max_percent_b: float = 0.9

    @property
    def name(self) -> str:
        return f"Bollinger %B < {self.max_percent_b}"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators.bollinger is None:
            return False

        return stock.indicators.bollinger.percent_b < self.max_percent_b


@icontract.invariant(lambda self: self.max_bandwidth > 0)
@dataclass(frozen=True)
class BollingerSqueezeCriterion:
    """Passes when band width relative to the middle band is below `max_bandwidth`, a volatility squeeze."""

    max_bandwidth: float = 0.1

    @property
    def name(self) -> str:
        return f"Bollinger Squeeze < {self.max_bandwidth}"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators.bollinger is None:
            return False

        return stock.indicators.bollinger.bandwidth < self.max_bandwidth
