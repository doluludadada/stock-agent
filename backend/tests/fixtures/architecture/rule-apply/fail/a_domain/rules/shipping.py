from dataclasses import dataclass


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


class DiscountRule:
    @staticmethod
    def decide(total: int) -> int:
        return total // 10
