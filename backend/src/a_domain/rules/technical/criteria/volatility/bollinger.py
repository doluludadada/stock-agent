from dataclasses import dataclass

import icontract

from a_domain.model.market.stock import Stock


# TODO: Add comment
@dataclass(frozen=True)
class BollingerPositionCriterion:
    @property
    def name(self) -> str:
        return "Bollinger Above Middle"

    def apply(self, stock: Stock) -> bool:
        bollinger = stock.indicators.bollinger

        if bollinger is None:
            return False

        if stock.current_price is None:
            return False

        return stock.current_price > bollinger.middle


@icontract.invariant(lambda self: self.max_percent_b > 0)
@dataclass(frozen=True)
class BollingerThresholdCriterion:
    max_percent_b: float = 0.9

    @property
    def name(self) -> str:
        return f"Bollinger %B < {self.max_percent_b}"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators.bollinger is None:
            return False

        percent_b = stock.indicators.bollinger.percent_b

        if percent_b is None:
            return False

        return percent_b < self.max_percent_b


@icontract.invariant(lambda self: self.max_bandwidth > 0)
@dataclass(frozen=True)
class BollingerSqueezeCriterion:
    max_bandwidth: float = 0.1

    @property
    def name(self) -> str:
        return f"Bollinger Squeeze < {self.max_bandwidth}"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators.bollinger is None:
            return False

        bandwidth = stock.indicators.bollinger.bandwidth

        if bandwidth is None:
            return False

        return bandwidth < self.max_bandwidth
