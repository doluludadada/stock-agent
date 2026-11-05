from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True)
class FreeShippingRule:
    minimum_total: int

    def apply(self, total: int) -> bool:
        return total >= self.minimum_total

    def explain(self) -> str:
        return f"free from {self.minimum_total}"

    @property
    def threshold(self) -> int:
        return self.minimum_total

    @classmethod
    def free_everywhere(cls) -> Self:
        return cls(minimum_total=0)


class DiscountRule:
    @property
    def rate(self) -> int:
        return 10

    @rate.setter
    def rate(self, value: int) -> None:
        print(value)

    @staticmethod
    def decide(total: int) -> int:
        return total // 10
