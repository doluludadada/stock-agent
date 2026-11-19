from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class Quote:
    stock_id: str
    price: float


@dataclass(frozen=True)
class Listing:
    stock_id: str
    board: str


@dataclass(frozen=True)
class Sector:
    name: str
