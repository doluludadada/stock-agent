import pydantic.dataclasses


@pydantic.dataclasses.dataclass(frozen=True)
class DiscountRule:
    percent: int

    def apply(self, total: int) -> int:
        return total * (100 - self.percent) // 100
