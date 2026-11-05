from dataclasses import dataclass


@dataclass(frozen=True)
class FreeShippingRule:
    minimum_total: int
    excluded_regions: frozenset[str]

    def __post_init__(self) -> None:
        if self.minimum_total < 0:
            raise ValueError("minimum_total must not be negative")

    def apply(self, total: int, region: str) -> bool:
        if self._is_excluded(region):
            return False

        return total >= self.minimum_total

    def _is_excluded(self, region: str) -> bool:
        return region in self.excluded_regions


@dataclass(frozen=True)
class ShippingQuote:
    total: int
    fee: int

    @property
    def charged(self) -> int:
        return self.total + self.fee


@dataclass(frozen=True)
class MovingAverageRule:
    windows: tuple[int, ...]

    @property
    def required_bars(self) -> int:
        return max(self.windows)

    def apply(self, closes: list[float]) -> bool:
        return len(closes) >= self.required_bars
