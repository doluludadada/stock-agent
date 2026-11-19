from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class Fill:
    quantity: int
    price: float


@dataclass
class Order:
    stock_id: str
    fills: list[Fill]
