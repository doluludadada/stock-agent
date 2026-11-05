from pydantic.dataclasses import dataclass


@dataclass
class Position:
    stock_id: str
    quantity: int
    average_cost: float
    mark_price: float | None = None

    @property
    def market_value(self) -> float:
        return self.quantity * (self.mark_price or self.average_cost)


@dataclass
class Account:
    account_id: str
    cash: float
    positions: list[Position]

    @property
    def equity(self) -> float:
        return self.cash + sum(position.market_value for position in self.positions)


@dataclass(frozen=True)
class AccountSnapshot:
    snapshot_id: str
    taken_at: str
    account: Account
