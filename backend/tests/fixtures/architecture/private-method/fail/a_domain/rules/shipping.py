from typing import Self

from pydantic import model_validator
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class FreeShippingRule:
    minimum_total: int
    excluded_regions: frozenset[str]

    @model_validator(mode="after")
    def _minimum_is_not_negative(self) -> Self:
        if self.minimum_total < 0:
            raise ValueError("minimum_total must not be negative")

        return self

    def apply(self, total: int, region: str) -> bool:
        if self._is_excluded(region):
            return False

        return total >= self.minimum_total

    def _is_excluded(self, region: str) -> bool:
        return region in self.excluded_regions

    @staticmethod
    def _free() -> int:
        return 0
