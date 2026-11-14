from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class TradeCost:
    fee: int
    tax: int


@dataclass(frozen=True)
class TradingCostRule:
    fee_rate: float

    def apply(self, amount: float) -> TradeCost:
        return trade_cost(amount, self.fee_rate)


def trade_cost(amount: float, fee_rate: float) -> TradeCost:
    return TradeCost(fee=int(amount * fee_rate), tax=0)
