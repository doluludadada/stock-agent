from dataclasses import dataclass
from enum import StrEnum


@dataclass
class Order:
    total: int


class OrderStatus(StrEnum):
    OPEN = "open"


@dataclass
class OrderLine:
    quantity: int
