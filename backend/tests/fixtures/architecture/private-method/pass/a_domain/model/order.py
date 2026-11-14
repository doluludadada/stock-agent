from pydantic import ConfigDict
from pydantic.dataclasses import dataclass


def move_to(order: Order, status: str) -> None:
    order.status = status


@dataclass(config=ConfigDict(validate_assignment=True))
class Order:
    status: str

    def cancel(self) -> None:
        move_to(self, "cancelled")

    def __str__(self) -> str:
        return self.status
