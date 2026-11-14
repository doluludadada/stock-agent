from dataclasses import dataclass
from typing import Self

from pydantic import field_validator, model_validator


def is_excluded(region: str, excluded_regions: frozenset[str]) -> bool:
    return region in excluded_regions


@dataclass(frozen=True)
class FreeShippingRule:
    minimum_total: int
    excluded_regions: frozenset[str]

    @model_validator(mode="after")
    def minimum_is_not_negative(self) -> Self:
        if self.minimum_total < 0:
            raise ValueError("minimum_total must not be negative")

        return self

    @field_validator("excluded_regions", mode="before")
    @classmethod
    def blank_is_no_region(cls, value: object) -> object:
        return value or frozenset()

    def apply(self, total: int, region: str) -> bool:
        if is_excluded(region, self.excluded_regions):
            return False

        return total >= self.minimum_total


@dataclass(frozen=True)
class ShippingQuote:
    total: int
    fee: int

    @model_validator(mode="after")
    def fee_is_not_above_total(self) -> Self:
        if self.fee > self.total:
            raise ValueError("fee must not be above total")

        return self

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
