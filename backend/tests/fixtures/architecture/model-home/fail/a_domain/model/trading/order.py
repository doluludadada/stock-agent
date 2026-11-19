from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class Order:
    stock_id: str
    quantity: int


@dataclass(frozen=True)
class ExchangeOrder:
    stock_id: str
    dealt_shares: int
