from dataclasses import dataclass, field

import icontract
from sqlmodel import SQLModel


@icontract.invariant(lambda self: self.total >= 0)
@dataclass(frozen=True)
class Order:
    total: int
    lines: list[int] = field(default_factory=list)


class Account(SQLModel):
    cash: float

    def __post_init__(self) -> None:
        pass
