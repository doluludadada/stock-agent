from typing import Self

from pydantic import model_validator
from pydantic.dataclasses import dataclass


def is_excluded(region: str, excluded_regions: frozenset[str]) -> bool:
    return region in excluded_regions


def _free() -> int:
    return 0


@dataclass(frozen=True)
class FreeShippingRule:
    minimum_total: int
    excluded_regions: frozenset[str]

    @model_validator(mode="after")
    def minimum_is_not_negative(self) -> Self:
        if self.minimum_total < _free():
            raise ValueError("minimum_total must not be negative")

        return self

    def apply(self, total: int, region: str) -> bool:
        if is_excluded(region, self.excluded_regions):
            return False

        return total >= self.minimum_total
