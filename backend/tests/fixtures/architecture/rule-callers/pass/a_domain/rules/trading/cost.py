from pydantic.dataclasses import dataclass

type Fee = int


@dataclass(frozen=True)
class TradeCost:
    fee: Fee
    tax: int

    @property
    def total(self) -> int:
        return self.fee + self.tax


@dataclass(frozen=True)
class TradingCostRule:
    fee_rate: float

    def apply(self, amount: float) -> TradeCost:
        return TradeCost(fee=int(amount * self.fee_rate), tax=0)
