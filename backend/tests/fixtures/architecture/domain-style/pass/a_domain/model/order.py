from dataclasses import replace
from enum import StrEnum
from typing import Annotated, Protocol, Self

from pydantic import Field
from pydantic.dataclasses import dataclass


class Color(StrEnum):
    RED = "red"


class Priced(Protocol):
    total: int


class OrderError(Exception):
    pass


@dataclass(frozen=True)
class Order:
    total: Annotated[int, Field(ge=0)]

    def doubled(self) -> Self:
        return replace(self, total=self.total * 2)
