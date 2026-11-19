from dataclasses import dataclass


@dataclass(frozen=True)
class OrderTotal:
    order_id: str
    total: float
