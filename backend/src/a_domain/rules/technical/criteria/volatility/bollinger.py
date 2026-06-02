from dataclasses import dataclass

from a_domain.model.market.stock import Stock


# TODO: Add comment
@dataclass(frozen=True)
class BollingerPositionCriterion:
    @property
    def name(self) -> str:
        return "Bollinger Above Middle"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.bollinger is None:
            return True

        bollinger = stock.indicators.bollinger

        if bollinger.middle is None or stock.current_price is None:
            return True

        return stock.current_price > bollinger.middle


@dataclass(frozen=True)
class BollingerThresholdCriterion:
    max_percent_b: float = 0.9

    @property
    def name(self) -> str:
        return f"Bollinger %B < {self.max_percent_b}"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.bollinger is None:
            return True

        percent_b = stock.indicators.bollinger.percent_b

        if percent_b is None:
            return True

        return percent_b < self.max_percent_b


@dataclass(frozen=True)
class BollingerSqueezeCriterion:
    max_bandwidth: float = 0.1

    @property
    def name(self) -> str:
        return f"Bollinger Squeeze < {self.max_bandwidth}"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.bollinger is None:
            return True

        bandwidth = stock.indicators.bollinger.bandwidth

        if bandwidth is None:
            return True

        return bandwidth < self.max_bandwidth
