from dataclasses import dataclass

from pydantic import Field
from sqlmodel import SQLModel

from a_domain.types.enums import OrderStatus

from .line import Line


@dataclass
class Order:
    status: OrderStatus
    lines: list[Line]
